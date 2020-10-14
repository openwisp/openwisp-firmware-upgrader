from unittest import mock

from celery.exceptions import SoftTimeLimitExceeded
from django.test import TransactionTestCase

from .. import tasks
from ..swapper import load_model
from .base import TestUpgraderMixin

BatchUpgradeOperation = load_model('BatchUpgradeOperation')
UpgradeOperation = load_model('UpgradeOperation')


class TestTasks(TestUpgraderMixin, TransactionTestCase):
    _mock_upgrade = 'openwisp_firmware_upgrader.upgraders.openwrt.OpenWrt.upgrade'
    _mock_connect = 'openwisp_controller.connection.models.DeviceConnection.connect'

    @mock.patch(_mock_upgrade, side_effect=SoftTimeLimitExceeded())
    @mock.patch(_mock_connect, return_value=True)
    @mock.patch(
        'openwisp_firmware_upgrader.base.models.AbstractUpgradeOperation.upgrade',
        side_effect=SoftTimeLimitExceeded(),
    )
    def test_upgrade_firmware_timeout(self, *args):
        device_fw = self._create_device_firmware(upgrade=True)
        self.assertEqual(UpgradeOperation.objects.count(), 1)
        uo = device_fw.image.upgradeoperation_set.first()
        self.assertEqual(uo.status, 'failed')
        self.assertIn('Operation timed out.', uo.log)

    @mock.patch(_mock_upgrade, return_value=True)
    @mock.patch(_mock_connect, return_value=True)
    @mock.patch(
        'openwisp_firmware_upgrader.base.models.AbstractDeviceFirmware.create_upgrade_operation',
        side_effect=SoftTimeLimitExceeded(),
    )
    def test_batch_upgrade_timeout(self, *args):
        env = self._create_upgrade_env()
        batch = BatchUpgradeOperation.objects.create(build=env['build2'])
        # will be executed synchronously due to CELERY_IS_EAGER = True
        tasks.batch_upgrade_operation.delay(batch_id=batch.pk, firmwareless=False)
        self.assertEqual(BatchUpgradeOperation.objects.count(), 1)
        batch = BatchUpgradeOperation.objects.first()
        self.assertEqual(batch.status, 'failed')

    @mock.patch(_mock_upgrade, return_value=True)
    @mock.patch(_mock_connect, return_value=True)
    @mock.patch('logging.Logger.warning')
    def test_upgrade_firmware_resilience(self, mocked_logger, *args):
        upgrade_op_id = UpgradeOperation().id
        tasks.upgrade_firmware.run(upgrade_op_id)
        mocked_logger.assert_called_with(
            f'The UpgradeOperation object with id {upgrade_op_id} has been deleted'
        )

    @mock.patch(_mock_upgrade, return_value=True)
    @mock.patch(_mock_connect, return_value=True)
    @mock.patch('logging.Logger.warning')
    def test_batch_upgrade_operation_resilience(self, mocked_logger, *args):
        batch_id = BatchUpgradeOperation().id
        tasks.batch_upgrade_operation.run(batch_id=batch_id, firmwareless=False)
        mocked_logger.assert_called_with(
            f'The BatchUpgradeOperation object with id {batch_id} has been deleted'
        )
