from celery import shared_task
from swapper import load_model

from . import settings as app_settings
from .exceptions import RecoverableFailure


@shared_task(
    bind=True, autoretry_for=(RecoverableFailure,), **app_settings.RETRY_OPTIONS
)
def upgrade_firmware(self, operation_id):
    """
    Calls the ``upgrade()`` method of an
    ``UpgradeOperation`` instance in the background
    """
    operation = load_model('firmware_upgrader', 'UpgradeOperation').objects.get(
        pk=operation_id
    )
    recoverable = self.request.retries < self.max_retries
    operation.upgrade(recoverable=recoverable)


@shared_task
def batch_upgrade_operation(build_id, firmwareless):
    """
    Calls the ``batch_upgrade()`` method of a
    ``Build`` instance in the background
    """
    build = load_model('firmware_upgrader', 'Build').objects.get(pk=build_id)
    build.batch_upgrade(firmwareless=firmwareless)
