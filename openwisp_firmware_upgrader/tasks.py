import logging
import random
from datetime import timedelta

import swapper
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext
from openwisp_notifications.signals import notify

from openwisp_utils.tasks import OpenwispCeleryTask

from . import settings as app_settings
from .exceptions import RecoverableFailure
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


@shared_task(base=OpenwispCeleryTask)
def retry_pending_upgrade(operation_id):
    UpgradeOperation = load_model("UpgradeOperation")
    updated = UpgradeOperation.objects.filter(pk=operation_id, status="pending").update(
        status="in-progress"
    )
    if not updated:
        return
    try:
        operation = UpgradeOperation.objects.select_related("device").get(
            pk=operation_id
        )
    except ObjectDoesNotExist:
        logger.warning(
            f"The UpgradeOperation object with id {operation_id} has been deleted"
        )
        return
    operation.log_line(
        _("Persistent retry #%(count)s starting.") % {"count": operation.retry_count},
        save=False,
    )
    if operation.device.is_deactivated():
        operation.status = "failed"
        operation.log_line(
            _("Device has been deactivated; persistent retry aborted."),
            save=False,
        )
        operation.save()
        return
    operation.save()
    upgrade_firmware.delay(operation.pk)


@shared_task(base=OpenwispCeleryTask)
def check_pending_upgrades():
    UpgradeOperation = load_model("UpgradeOperation")
    due_ids = UpgradeOperation.objects.filter(
        status="pending", next_retry_at__lte=timezone.now()
    ).values_list("pk", flat=True)
    jitter = app_settings.PERSISTENT_RETRY_OPTIONS["dispatch_jitter"]
    for op_id in due_ids:
        retry_pending_upgrade.apply_async(
            args=[op_id], countdown=random.uniform(0, jitter)
        )


@shared_task(base=OpenwispCeleryTask)
def send_pending_upgrade_reminders():
    BatchUpgradeOperation = load_model("BatchUpgradeOperation")
    period = app_settings.PERSISTENT_REMINDER_PERIOD
    threshold = timezone.now() - timedelta(seconds=period)
    due_condition = Q(last_reminder_at__lte=threshold) | Q(
        last_reminder_at__isnull=True, created__lte=threshold
    )
    qs = (
        BatchUpgradeOperation.objects.filter(
            status="in-progress", upgradeoperation__status="pending"
        )
        .filter(due_condition)
        .distinct()
    )
    for batch in qs:
        claimed = (
            BatchUpgradeOperation.objects.filter(pk=batch.pk)
            .filter(due_condition)
            .update(last_reminder_at=timezone.now())
        )
        if not claimed:
            continue
        pending_count = batch.upgradeoperation_set.filter(status="pending").count()
        if not pending_count:
            continue
        notify.send(
            sender=batch,
            type="generic_message",
            target=batch,
            description=ngettext(
                "%(count)d device is still pending in mass upgrade %(batch)s.",
                "%(count)d devices are still pending in mass upgrade %(batch)s.",
                pending_count,
            )
            % {"count": pending_count, "batch": batch},
        )
