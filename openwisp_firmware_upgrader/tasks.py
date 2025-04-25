import logging
import os

import swapper
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.core.exceptions import ObjectDoesNotExist
from django.utils.translation import gettext_lazy as _

from openwisp_utils.tasks import OpenwispCeleryTask

from . import settings as app_settings
from .exceptions import RecoverableFailure
from .private_storage.storage import file_system_private_storage
from .swapper import load_model

logger = logging.getLogger(__name__)


@shared_task(base=OpenwispCeleryTask, bind=True)
def delete_firmware_files(self, file_paths):
    """
    Deletes firmware files from storage in the background
    """
    logger.info(f"Starting delete_firmware_files task with paths: {file_paths}")
    storage = app_settings.PRIVATE_STORAGE_INSTANCE
    if not storage:
        logger.error("No storage instance configured")
        return
    logger.info(f"Using storage backend: {storage.__class__.__name__}")
    logger.info(f"Storage location: {storage.location}")

    for path in file_paths:
        logger.info(f"Attempting to delete file: {path}")
        try:
            try:
                exists = storage.exists(path)
                logger.info(f"File exists: {exists}")
                if exists:
                    full_path = storage.path(path)
                    logger.info(f"Full path: {full_path}")
                    storage.delete(path)
                    logger.info(f"Successfully deleted file: {path}")
                else:
                    logger.warning(f"File does not exist: {path}")

                # Try to delete parent directory if empty
                dir_path = '/'.join(path.split('/')[:-1])
                if dir_path:
                    logger.info(f"Attempting to delete directory: {dir_path}")
                    try:
                        if storage.exists(dir_path):
                            full_dir_path = storage.path(dir_path)
                            logger.info(f"Full directory path: {full_dir_path}")
                            if not os.listdir(
                                full_dir_path
                            ):  # Check if directory is empty
                                storage.delete(dir_path)
                                logger.info(
                                    f"Successfully deleted directory: {dir_path}"
                                )
                            else:
                                logger.info(
                                    f"Directory not empty, skipping: {dir_path}"
                                )
                    except OSError as error:
                        logger.warning(f'Error deleting directory {dir_path}: {error}')
            except Exception as e:
                logger.error(f'Error processing path {path}: {str(e)}')
        except Exception as e:
            logger.warning(f'Error deleting file {path}: {e}')


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


@shared_task(base=OpenwispCeleryTask, bind=True)
def create_device_firmware(self, device_id):
    DeviceFirmware = load_model('DeviceFirmware')
    Device = swapper.load_model('config', 'Device')

    qs = DeviceFirmware.objects.filter(device_id=device_id)
    if qs.exists():
        return

    device = Device.objects.get(pk=device_id)
    DeviceFirmware.create_for_device(device)


@shared_task(base=OpenwispCeleryTask, bind=True)
def create_all_device_firmwares(self, firmware_image_id):
    DeviceFirmware = load_model('DeviceFirmware')
    FirmwareImage = load_model('FirmwareImage')
    Device = swapper.load_model('config', 'Device')

    fw_image = FirmwareImage.objects.select_related('build').get(pk=firmware_image_id)

    queryset = Device.objects.filter(os=fw_image.build.os)
    for device in queryset.iterator():
        DeviceFirmware.create_for_device(device, fw_image)
