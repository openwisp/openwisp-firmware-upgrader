import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.core.exceptions import ObjectDoesNotExist
from django.utils.translation import gettext_lazy as _

from openwisp_controller.config.models import Device

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
        operation = load_model('UpgradeOperation').objects.get(pk=operation_id)
        recoverable = self.request.retries < self.max_retries
        operation.upgrade(recoverable=recoverable)
    except SoftTimeLimitExceeded:
        operation.status = 'failed'
        operation.log_line(_('Operation timed out.'))
        logger.warning('SoftTimeLimitExceeded raised in upgrade_firmware task')
    except ObjectDoesNotExist:
        logger.warning(
            f'The UpgradeOperation object with id {operation_id} has been deleted'
        )


@shared_task(bind=True, soft_time_limit=app_settings.TASK_TIMEOUT)
def batch_upgrade_operation(self, batch_id, firmwareless):
    """
    Calls the ``batch_upgrade()`` method of a
    ``Build`` instance in the background
    """
    try:
        batch_operation = load_model('BatchUpgradeOperation').objects.get(pk=batch_id)
        batch_operation.upgrade(firmwareless=firmwareless)
    except SoftTimeLimitExceeded:
        batch_operation.status = 'failed'
        batch_operation.save()
        logger.warning('SoftTimeLimitExceeded raised in batch_upgrade_operation task')
    except ObjectDoesNotExist:
        logger.warning(
            f'The BatchUpgradeOperation object with id {batch_id} has been deleted'
        )


@shared_task(bind=True)
def create_device_firmware(self, device_id):
    DeviceFirmware = load_model('DeviceFirmware')

    qs = DeviceFirmware.objects.filter(device_id=device_id)
    if qs.exists():
        return

    device = Device.objects.get(pk=device_id)
    DeviceFirmware.create_for_device(device)


@shared_task(bind=True)
def create_all_device_firmwares(self, firmware_image_id):
    DeviceFirmware = load_model('DeviceFirmware')
    FirmwareImage = load_model('FirmwareImage')

    fw_image = FirmwareImage.objects.select_related('build').get(pk=firmware_image_id)
    queryset = Device.objects.filter(os=fw_image.build.os)
    for device in queryset.iterator():
        DeviceFirmware.create_for_device(device, fw_image)
