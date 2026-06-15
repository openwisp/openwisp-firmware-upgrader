import logging

import swapper
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.core.exceptions import ObjectDoesNotExist
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from openwisp_notifications.signals import notify

from openwisp_utils.tasks import OpenwispCeleryTask

from . import settings as app_settings
from .exceptions import RecoverableFailure
from .extractors.exceptions import DecompressionLimitExceeded, UnsupportedImageError
from .extractors.openwrt import OpenWrtMetadataExtractor
from .swapper import load_model

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(RecoverableFailure,),
    soft_time_limit=app_settings.TASK_TIMEOUT,
    **app_settings.RETRY_OPTIONS,
)
def upgrade_firmware(self, operation_id):
    """
    Calls the ``upgrade()`` method of an
    ``UpgradeOperation`` instance in the background
    """
    try:
        operation = load_model("UpgradeOperation").objects.get(pk=operation_id)
        recoverable = self.request.retries < self.max_retries
        operation.upgrade(recoverable=recoverable)
    except SoftTimeLimitExceeded:
        operation.status = "failed"
        operation.log_line(_("Operation timed out."))
        logger.warning("SoftTimeLimitExceeded raised in upgrade_firmware task")
    except ObjectDoesNotExist:
        logger.warning(
            f"The UpgradeOperation object with id {operation_id} has been deleted"
        )


@shared_task(bind=True, soft_time_limit=app_settings.TASK_TIMEOUT)
def batch_upgrade_operation(self, batch_id, firmwareless):
    """
    Calls the ``batch_upgrade()`` method of a
    ``Build`` instance in the background
    """
    try:
        batch_operation = load_model("BatchUpgradeOperation").objects.get(pk=batch_id)
        batch_operation.upgrade(firmwareless=firmwareless)
    except SoftTimeLimitExceeded:
        batch_operation.status = "failed"
        batch_operation.save()
        logger.warning("SoftTimeLimitExceeded raised in batch_upgrade_operation task")
    except ObjectDoesNotExist:
        logger.warning(
            f"The BatchUpgradeOperation object with id {batch_id} has been deleted"
        )


@shared_task(base=OpenwispCeleryTask, bind=True)
def create_device_firmware(self, device_id):
    DeviceFirmware = load_model("DeviceFirmware")
    Device = swapper.load_model("config", "Device")

    qs = DeviceFirmware.objects.filter(device_id=device_id)
    if qs.exists():
        return

    device = Device.objects.get(pk=device_id)
    DeviceFirmware.create_for_device(device)


@shared_task(base=OpenwispCeleryTask, bind=True)
def create_all_device_firmwares(self, firmware_image_id):
    DeviceFirmware = load_model("DeviceFirmware")
    FirmwareImage = load_model("FirmwareImage")
    Device = swapper.load_model("config", "Device")

    fw_image = FirmwareImage.objects.select_related("build").get(pk=firmware_image_id)

    queryset = Device.objects.filter(os=fw_image.build.os)
    for device in queryset.iterator():
        DeviceFirmware.create_for_device(device, fw_image)


@shared_task(base=OpenwispCeleryTask)
def delete_firmware_files(files_to_delete):
    """
    Celery task to delete firmware image files and their parent directories if empty.

    Args:
        files_to_delete (list[str]): A list of file paths (relative to the storage backend)
                                     that should be deleted.
    """
    FirmwareImage = load_model("FirmwareImage")
    for file_path in files_to_delete:
        FirmwareImage._remove_file(file_path)


def _compat_blocks_pairing(compat_version):
    try:
        major, minor = (int(x) for x in str(compat_version).split("."))
        return (major, minor) > (1, 0)
    except (ValueError, AttributeError, TypeError):
        return False


@shared_task(bind=True, soft_time_limit=app_settings.TASK_TIMEOUT)
def extract_firmware_metadata(self, image_pk):
    FirmwareImage = load_model("FirmwareImage")

    try:
        image = FirmwareImage.objects.get(pk=image_pk)
    except FirmwareImage.DoesNotExist:
        logger.warning(
            "extract_firmware_metadata: FirmwareImage pk=%s not found, skipping",
            image_pk,
        )
        return

    updated = FirmwareImage.objects.filter(
        pk=image_pk,
        extraction_status=FirmwareImage.STATUS_UNCONFIRMED,
    ).update(extraction_status=FirmwareImage.STATUS_IN_PROGRESS)
    if not updated:
        return
    log_lines = [f"[+] Analyzing: {image.file.name}"]
    update = {}

    try:
        extractor_class = getattr(
            image.build.category.__class__,
            "metadata_extractor_class",
            OpenWrtMetadataExtractor,
        )
        meta = extractor_class(image.file.path).extract()
        log_lines.append("[+] extraction: success")
        update = {
            "extraction_status": FirmwareImage.STATUS_SUCCESS,
            "extraction_log": "\n".join(log_lines),
            "board": meta.get("model", ""),
            "compatible": meta.get("compatible", []),
            "target": meta.get("target", ""),
            "fw_version": meta.get("version", ""),
            "compat_version": meta.get("compat_version", ""),
            "source": meta.get("source", "fwtool"),
        }

    except SoftTimeLimitExceeded:
        log_lines.append(f"[!] Task timed out after {app_settings.TASK_TIMEOUT}s.")
        update = {
            "extraction_status": FirmwareImage.STATUS_FAILED,
            "failure_reason": FirmwareImage.FAILURE_TIMEOUT,
            "extraction_log": "\n".join(log_lines),
        }
        logger.warning(
            "extract_firmware_metadata: soft time limit exceeded for pk=%s",
            image_pk,
        )

    except DecompressionLimitExceeded as exc:
        log_lines.append(f"[!] {exc}")
        update = {
            "extraction_status": FirmwareImage.STATUS_FAILED,
            "failure_reason": FirmwareImage.FAILURE_OOM,
            "extraction_log": "\n".join(log_lines),
        }
        logger.warning(
            "extract_firmware_metadata: decompression limit exceeded for pk=%s - %s",
            image_pk,
            exc,
        )

    except UnsupportedImageError as exc:
        log_lines.append(f"[-] fwtool: {exc}")
        log_lines.append("[!] Extraction failed. Manual input required.")
        update = {
            "extraction_status": FirmwareImage.STATUS_FAILED,
            "failure_reason": FirmwareImage.FAILURE_UNSUPPORTED,
            "extraction_log": "\n".join(log_lines),
        }
        logger.warning(
            "extract_firmware_metadata: unsupported image pk=%s - %s",
            image_pk,
            exc,
        )

    except Exception:
        log_lines.append("[!] Unexpected error during extraction.")
        update = {
            "extraction_status": FirmwareImage.STATUS_INVALID,
            "failure_reason": FirmwareImage.FAILURE_INVALID,
            "extraction_log": "\n".join(log_lines),
        }
        logger.exception(
            "extract_firmware_metadata: unhandled exception for pk=%s",
            image_pk,
        )

    FirmwareImage.objects.filter(pk=image_pk).update(**update)

    if update.get("extraction_status") not in (
        FirmwareImage.STATUS_SUCCESS,
        FirmwareImage.STATUS_IN_PROGRESS,
    ):
        try:
            image = FirmwareImage.objects.select_related(
                "build", "build__category"
            ).get(pk=image_pk)
            build_opts = image.build._meta
            admin_url = reverse(
                f"admin:{build_opts.app_label}_{build_opts.model_name}_change",
                args=[str(image.build_id)],
            )
            notify.send(
                sender=image,
                type="generic_message",
                level="error",
                url=admin_url,
                target=image.build,
                message=_(
                    'Metadata extraction failed for <a href="{admin_url}">{image}</a>: '
                    "{reason}. You can manually enter metadata or re-upload the image."
                ).format(
                    url=admin_url,
                    image=image,
                    reason=update.get("failure_reason", "unknown error"),
                ),
            )
        except Exception:
            logger.exception("Failed to send extraction failure notification")

    try:
        fresh = FirmwareImage.objects.select_related("build").get(pk=image_pk)
        fresh.build._update_extraction_status()
    except Exception:
        logger.exception(
            "Failed to update build extraction status for image %s", image_pk
        )

    if update.get("extraction_status") == FirmwareImage.STATUS_SUCCESS:
        compat = update.get("compat_version", "")
        if _compat_blocks_pairing(compat):
            logger.info(
                "Auto-pairing skipped for image %s: compat_version %s > 1.0",
                image_pk,
                compat,
            )
        else:
            create_all_device_firmwares.delay(str(image_pk))
