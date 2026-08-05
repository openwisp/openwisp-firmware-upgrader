import logging
import os
import shutil
import tempfile

import swapper
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.core.exceptions import ObjectDoesNotExist
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from openwisp_notifications.signals import notify

from openwisp_utils.tasks import OpenwispCeleryTask

from . import settings as app_settings
from .exceptions import RecoverableFailure
from .extractors.exceptions import DecompressionLimitExceeded, UnsupportedImageError
from .swapper import load_model
from .websockets import FirmwareExtractionPublisher

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

    fw_image = FirmwareImage.objects.select_related("build__category").get(
        pk=firmware_image_id
    )

    if _compat_blocks_pairing(fw_image.compat_version):
        logger.info(
            "Auto-pairing skipped for image %s: compat_version %s > 1.0",
            firmware_image_id,
            fw_image.compat_version,
        )
        return

    queryset = Device.objects.filter(os=fw_image.build.os)
    if fw_image.board:
        queryset = queryset.filter(model=fw_image.board)
    org_id = fw_image.build.category.organization_id
    if org_id:
        queryset = queryset.filter(organization_id=org_id)
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


def _get_image_admin_url(image):
    opts = image._meta
    return (
        reverse(
            f"admin:{opts.app_label}_{opts.model_name}_change",
            args=[str(image.pk)],
        )
        + "#device-metadata"
    )


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

    file_name = image.file.name
    updated = FirmwareImage.objects.filter(
        pk=image_pk,
        file=file_name,
        extraction_status=FirmwareImage.STATUS_UNCONFIRMED,
    ).update(extraction_status=FirmwareImage.STATUS_IN_PROGRESS)
    if not updated:
        return
    image = FirmwareImage.objects.get(pk=image_pk, file=file_name)
    log_lines = [f"[+] Analyzing: {os.path.basename(image.file.name)}"]
    update = {}

    try:
        extractor_class = image.build.category.metadata_extractor_class
        with tempfile.NamedTemporaryFile(
            suffix=f"-{os.path.basename(image.file.name)}"
        ) as tmp:
            with image.file.open("rb") as file_obj:
                shutil.copyfileobj(file_obj, tmp)
            tmp.flush()
            meta = extractor_class(tmp.name).extract()
        board = meta.get("model") or ""
        if meta.get("source") == "dtb":
            log_lines.append(
                "[-] fwtool: no metadata trailer found, fell back to DTB scan"
            )
            log_lines.append("[+] DTB scan: board and compatible extracted")
            log_lines.append(
                "[!] Target and firmware version unavailable from DTB. "
                "Manual input is required."
            )
        else:
            log_lines.append("[+] fwtool: metadata trailer found")
        if not board:
            log_lines.append(
                "[!] Extraction completed but no board/model could be "
                "determined. Manual input is required. "
            )
            update = {
                "extraction_status": FirmwareImage.STATUS_FAILED,
                "failure_reason": FirmwareImage.FAILURE_UNSUPPORTED,
                "extraction_log": "\n".join(log_lines),
                "board": meta.get("model") or "",
                "compatible": "\n".join(meta.get("compatible", [])),
                "target": meta.get("target", ""),
                "fw_version": meta.get("version", ""),
                "compat_version": meta.get("compat_version", ""),
                "source": meta.get("source", "fwtool"),
            }
        else:
            log_lines.append("[+] extraction: success")
            update = {
                "extraction_status": FirmwareImage.STATUS_SUCCESS,
                "extraction_log": "\n".join(log_lines),
                "board": meta.get("model") or "",
                "compatible": "\n".join(meta.get("compatible", [])),
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

    try:
        completed = FirmwareImage.objects.filter(
            pk=image_pk,
            file=file_name,
            extraction_status=FirmwareImage.STATUS_IN_PROGRESS,
        ).update(**update)
    except Exception:
        logger.exception(
            "extract_firmware_metadata: failed to persist result for pk=%s",
            image_pk,
        )
        FirmwareImage.objects.filter(
            pk=image_pk,
            extraction_status=FirmwareImage.STATUS_IN_PROGRESS,
        ).update(
            extraction_status=FirmwareImage.STATUS_INVALID,
            failure_reason=FirmwareImage.FAILURE_INVALID,
        )
        try:
            fresh = FirmwareImage.objects.select_related("build").get(pk=image_pk)
            fresh.build._update_extraction_status()
        except Exception:
            logger.exception(
                "extract_firmware_metadata:failed to update build status after fallback for pk=%s",
                image_pk,
            )
        return
    if not completed:
        return

    _terminal = {
        FirmwareImage.STATUS_SUCCESS,
        FirmwareImage.STATUS_FAILED,
        FirmwareImage.STATUS_INVALID,
    }
    if update.get("extraction_status") in _terminal:
        try:
            FirmwareExtractionPublisher(image_pk).publish_status(
                update["extraction_status"]
            )
        except Exception:
            logger.exception(
                "Failed to publish extraction status via WebSocket for image %s",
                image_pk,
            )
    try:
        fresh = FirmwareImage.objects.select_related("build", "build__category").get(
            pk=image_pk
        )
    except Exception:
        logger.exception(
            "Failed to re-fetch image %s for post-extraction steps", image_pk
        )
        return

    if update.get("extraction_status") in (
        FirmwareImage.STATUS_FAILED,
        FirmwareImage.STATUS_INVALID,
    ):
        try:
            admin_url = _get_image_admin_url(fresh)
            failure_reason_choices = dict(FirmwareImage.FAILURE_REASON_CHOICES)
            reason_display = failure_reason_choices.get(
                update.get("failure_reason", ""),
                _("unknown error"),
            )
            notify.send(
                sender=fresh.build.category.organization or fresh,
                type="generic_message",
                level="error",
                url=admin_url,
                target=fresh,
                message=format_html(
                    _(
                        'Metadata extraction failed for <a href="{url}">{image}</a>: '
                        "{reason}. Enter the metadata manually or re-upload the image."
                    ),
                    url=admin_url,
                    image=fresh,
                    reason=reason_display,
                ),
            )
        except Exception:
            logger.exception("Failed to send extraction failure notification")

    if (
        update.get("extraction_status") == FirmwareImage.STATUS_SUCCESS
        and update.get("source") == "dtb"
    ):
        try:
            admin_url = _get_image_admin_url(fresh)
            notify.send(
                sender=fresh.build.category.organization or fresh,
                type="generic_message",
                level="warning",
                url=admin_url,
                target=fresh,
                message=format_html(
                    _(
                        'Partial metadata extracted via DTB scan for <a href="{url}">{image}</a>. '
                        "Manual input required."
                    ),
                    url=admin_url,
                    image=fresh,
                ),
            )
        except Exception:
            logger.exception("Failed to send DTB extraction notification")

    try:
        fresh.build._update_extraction_status()
    except Exception:
        logger.exception(
            "Failed to update build extraction status for image %s", image_pk
        )

    if update.get("extraction_status") == FirmwareImage.STATUS_SUCCESS:
        create_all_device_firmwares.delay(str(image_pk))


@shared_task(base=OpenwispCeleryTask)
def queue_unconfirmed_extractions():
    FirmwareImage = load_model("FirmwareImage")
    pks = (
        FirmwareImage.objects.filter(extraction_status=FirmwareImage.STATUS_UNCONFIRMED)
        .values_list("pk", flat=True)
        .iterator()
    )
    for pk in pks:
        extract_firmware_metadata.delay(pk)
