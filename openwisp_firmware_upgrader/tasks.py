from celery import shared_task
from swapper import load_model


@shared_task
def upgrade_firmware(operation_id):
    """
    Calls the ``upgrade()`` method of an
    ``UpgradeOperation`` instance in the background
    """
    operation = load_model('firmware_upgrader', 'UpgradeOperation').objects.get(
        pk=operation_id
    )
    operation.upgrade()


@shared_task
def batch_upgrade_operation(build_id, firmwareless):
    """
    Calls the ``batch_upgrade()`` method of a
    ``Build`` instance in the background
    """
    build = load_model('firmware_upgrader', 'Build').objects.get(pk=build_id)
    build.batch_upgrade(firmwareless=firmwareless)
