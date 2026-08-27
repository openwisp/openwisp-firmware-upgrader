import os
import shutil
import tempfile
from datetime import timedelta
from functools import partial
from itertools import islice

import swapper
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from celery.utils.log import get_task_logger
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from openwisp_notifications.signals import notify

from openwisp_utils.tasks import OpenwispCeleryTask

from . import settings as app_settings
from .exceptions import RecoverableFailure
from .extractors.exceptions import DecompressionLimitExceeded, UnsupportedImageError
from .swapper import load_model
from .utils import compat_blocks_pairing
from .websockets import FirmwareExtractionPublisher

logger = get_task_logger(__name__)


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

    if compat_blocks_pairing(fw_image.compat_version):
        logger.info(
            "Auto-pairing skipped for image %s: compat_version %s > 1.0",
            firmware_image_id,
            fw_image.compat_version,
        )
        return

    if not fw_image.board:
        logger.info(
            "Auto-pairing skipped for image %s: board is empty",
            firmware_image_id,
        )
        return

    queryset = Device.objects.filter(os=fw_image.build.os)
    queryset = queryset.filter(model=fw_image.board)
    queryset = queryset.filter(devicefirmware__isnull=True)
    queryset = queryset.exclude(_is_deactivated=True)
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


def _get_image_admin_url(image):
    opts = image._meta
    return (
        reverse(
            f"admin:{opts.app_label}_{opts.model_name}_change",
            args=[str(image.pk)],
        )
        + "#device-metadata"
    )


def _notify_image(image, level, message_template, **message_kwargs):
    try:
        admin_url = _get_image_admin_url(image)
        notify.send(
            sender=image.build.category.organization or image,
            type="generic_message",
            level=level,
            url=admin_url,
            target=image,
            message=format_html(
                message_template, url=admin_url, image=image, **message_kwargs
            ),
        )
    except Exception:
        logger.exception(
            "Failed to send %s extraction notification for image %s", level, image.pk
        )


def _finalize_failed_extraction(
    image_pk, status, failure_reason, update_status_log_message
):
    FirmwareImage = load_model("FirmwareImage")
    try:
        FirmwareExtractionPublisher(image_pk).publish_status(status)
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
    failure_reason_choices = dict(FirmwareImage.FAILURE_REASON_CHOICES)
    reason_display = failure_reason_choices.get(failure_reason, _("unknown error"))
    _notify_image(
        fresh,
        "error",
        _(
            'Metadata extraction failed for <a href="{url}">{image}</a>: '
            "{reason}. Enter the metadata manually or re-upload the image."
        ),
        reason=reason_display,
    )
    try:
        fresh.build.update_extraction_status()
    except Exception:
        logger.exception(update_status_log_message, image_pk)


@shared_task(bind=True, soft_time_limit=app_settings.TASK_TIMEOUT)
def extract_firmware_metadata(self, image_pk):
    FirmwareImage = load_model("FirmwareImage")

    try:
        image = FirmwareImage.objects.get(pk=image_pk)
    except FirmwareImage.DoesNotExist:
        logger.warning(
            "FirmwareImage pk=%s not found, skipping",
            image_pk,
        )
        return

    file_name = image.file.name
    updated = FirmwareImage.objects.filter(
        pk=image_pk,
        file=file_name,
        extraction_status=FirmwareImage.STATUS_UNCONFIRMED,
    ).update(
        extraction_status=FirmwareImage.STATUS_IN_PROGRESS,
        extraction_claimed_at=timezone.now(),
    )
    if not updated:
        return

    try:
        image = FirmwareImage.objects.get(pk=image_pk, file=file_name)
    except FirmwareImage.DoesNotExist:
        # the file was replaced concurrently, release the claim so the
        # extraction scheduled by the replacement can claim the row
        FirmwareImage.objects.filter(
            pk=image.pk,
            extraction_status=FirmwareImage.STATUS_IN_PROGRESS,
        ).update(
            extraction_status=FirmwareImage.STATUS_UNCONFIRMED,
            extraction_claimed_at=None,
        )
        logger.warning(
            "file changed concurrently for pk=%s, skipping",
            image_pk,
        )
        return
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
        update = {
            "board": board,
            "compatible": "\n".join(meta.get("compatible") or []),
            "target": meta.get("target", ""),
            "fw_version": meta.get("version", ""),
            "compat_version": meta.get("compat_version", ""),
            "source": meta.get("source", "fwtool"),
        }
        if not board:
            log_lines.append(
                "[!] Extraction completed but no board/model could be "
                "determined. Manual input is required. "
            )
            update["extraction_status"] = FirmwareImage.STATUS_FAILED
            update["failure_reason"] = FirmwareImage.FAILURE_UNSUPPORTED
        elif meta.get("source") == "dtb":
            log_lines.append("[+] extraction: incomplete, manual input required")
            update["extraction_status"] = FirmwareImage.STATUS_INCOMPLETE
        else:
            log_lines.append("[+] extraction: success")
            update["extraction_status"] = FirmwareImage.STATUS_SUCCESS
        update["extraction_log"] = "\n".join(log_lines)

    except SoftTimeLimitExceeded:
        log_lines.append(f"[!] Task timed out after {app_settings.TASK_TIMEOUT}s.")
        update = {
            "extraction_status": FirmwareImage.STATUS_FAILED,
            "failure_reason": FirmwareImage.FAILURE_TIMEOUT,
            "extraction_log": "\n".join(log_lines),
        }
        logger.warning(
            "soft time limit exceeded for pk=%s",
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
            "decompression limit exceeded for pk=%s - %s",
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
            "unsupported image pk=%s - %s",
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
            "unhandled exception for pk=%s",
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
            "failed to persist result for pk=%s",
            image_pk,
        )
        log_lines.append("[!] Failed to save extraction result. Manual input required.")
        FirmwareImage.objects.filter(
            pk=image_pk,
            extraction_status=FirmwareImage.STATUS_IN_PROGRESS,
        ).update(
            extraction_status=FirmwareImage.STATUS_INVALID,
            failure_reason=FirmwareImage.FAILURE_INVALID,
            extraction_log="\n".join(log_lines),
        )
        _finalize_failed_extraction(
            image_pk,
            FirmwareImage.STATUS_INVALID,
            FirmwareImage.FAILURE_INVALID,
            "failed to update build status for pk=%s",
        )
        return

    if not completed:
        return

    _terminal = {
        FirmwareImage.STATUS_SUCCESS,
        FirmwareImage.STATUS_INCOMPLETE,
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
        failure_reason_choices = dict(FirmwareImage.FAILURE_REASON_CHOICES)
        reason_display = failure_reason_choices.get(
            update.get("failure_reason", ""),
            _("unknown error"),
        )
        _notify_image(
            fresh,
            "error",
            _(
                'Metadata extraction failed for <a href="{url}">{image}</a>: '
                "{reason}. Enter the metadata manually or re-upload the image."
            ),
            reason=reason_display,
        )

    if update.get("extraction_status") == FirmwareImage.STATUS_INCOMPLETE:
        _notify_image(
            fresh,
            "warning",
            _(
                'Partial metadata extracted for <a href="{url}">{image}</a>. '
                "Enter missing metadata manually if needed."
            ),
        )

    try:
        fresh.build.update_extraction_status()
    except Exception:
        logger.exception(
            "Failed to update build extraction status for image %s", image_pk
        )

    if update.get("extraction_status") in (
        FirmwareImage.STATUS_SUCCESS,
        FirmwareImage.STATUS_INCOMPLETE,
    ):
        transaction.on_commit(partial(create_all_device_firmwares.delay, str(image.pk)))


@shared_task(base=OpenwispCeleryTask)
def _dispatch_unconfirmed_extractions_chunk(pks):
    for pk in pks:
        extract_firmware_metadata.delay(pk)


@shared_task(base=OpenwispCeleryTask)
def queue_unconfirmed_extractions():
    FirmwareImage = load_model("FirmwareImage")
    # dispatch in chunks instead of one .delay() per pk, to avoid flooding
    # the broker on installs with a large backlog of unconfirmed images
    chunk_size = app_settings.QUEUE_UNCONFIRMED_CHUNK_SIZE
    pks_iterator = (
        FirmwareImage.objects.filter(extraction_status=FirmwareImage.STATUS_UNCONFIRMED)
        .values_list("pk", flat=True)
        .iterator(chunk_size=chunk_size)
    )
    while chunk := list(islice(pks_iterator, chunk_size)):
        _dispatch_unconfirmed_extractions_chunk.delay(chunk)


@shared_task(base=OpenwispCeleryTask)
def reclaim_stale_extractions():
    FirmwareImage = load_model("FirmwareImage")
    cutoff = timezone.now() - timedelta(seconds=app_settings.EXTRACTION_CLAIM_TIMEOUT)
    stale_pks = list(
        FirmwareImage.objects.filter(extraction_status=FirmwareImage.STATUS_IN_PROGRESS)
        .filter(
            Q(extraction_claimed_at__lt=cutoff) | Q(extraction_claimed_at__isnull=True)
        )
        .values_list("pk", flat=True)
    )
    for pk in stale_pks:
        rows_updated = FirmwareImage.objects.filter(
            pk=pk, extraction_status=FirmwareImage.STATUS_IN_PROGRESS
        ).update(
            extraction_status=FirmwareImage.STATUS_FAILED,
            failure_reason=FirmwareImage.FAILURE_TIMEOUT,
            extraction_log=(
                "[!] Extraction task did not complete (worker crash or hard "
                "timeout). Manual input required."
            ),
        )
        if not rows_updated:
            continue
        _finalize_failed_extraction(
            pk,
            FirmwareImage.STATUS_FAILED,
            FirmwareImage.FAILURE_TIMEOUT,
            "failed to update build status for pk=%s",
        )
