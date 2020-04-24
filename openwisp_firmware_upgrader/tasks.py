import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from swapper import load_model

from . import settings as app_settings
from .exceptions import RecoverableFailure

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(RecoverableFailure,),
    soft_time_limit=app_settings.TASK_TIMEOUT,
    **app_settings.RETRY_OPTIONS
)
def upgrade_firmware(self, operation_id):
    """
    Calls the ``upgrade()`` method of an
    ``UpgradeOperation`` instance in the background
    """
    try:
        operation = load_model('firmware_upgrader', 'UpgradeOperation').objects.get(
            pk=operation_id
        )
        recoverable = self.request.retries < self.max_retries
        operation.upgrade(recoverable=recoverable)
    except SoftTimeLimitExceeded:
        operation.status = 'failed'
        operation.log_line('Operation timed out.')
        logger.warn('SoftTimeLimitExceeded raised in upgrade_firmware task')


@shared_task(bind=True, soft_time_limit=app_settings.TASK_TIMEOUT)
def batch_upgrade_operation(self, build_id, firmwareless):
    """
    Calls the ``batch_upgrade()`` method of a
    ``Build`` instance in the background
    """
    try:
        build = load_model('firmware_upgrader', 'Build').objects.get(pk=build_id)
        build.batch_upgrade(firmwareless=firmwareless)
    except SoftTimeLimitExceeded:
        batch_operation = build.batchupgradeoperation_set.order_by('-created').last()
        batch_operation.status = 'failed'
        batch_operation.save()
        logger.warn('SoftTimeLimitExceeded raised in batch_upgrade_operation task')
