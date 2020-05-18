from unittest import mock

from celery.exceptions import SoftTimeLimitExceeded
from django.test import TransactionTestCase

from .. import tasks
from ..swapper import load_model
from .base import TestUpgraderMixin

BatchUpgradeOperation = load_model('BatchUpgradeOperation')
UpgradeOperation = load_model('UpgradeOperation')


class TestTasks(TestUpgraderMixin, TransactionTestCase):
    _mock_updrade = 'openwisp_firmware_upgrader.upgraders.openwrt.OpenWrt.upgrade'
    _mock_connect = 'openwisp_controller.connection.models.DeviceConnection.connect'

    @mock.patch(_mock_updrade, side_effect=SoftTimeLimitExceeded())
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

    @mock.patch(_mock_updrade, return_value=True)
    @mock.patch(_mock_connect, return_value=True)
    @mock.patch(
        'openwisp_firmware_upgrader.base.models.AbstractDeviceFirmware.create_upgrade_operation',
        side_effect=SoftTimeLimitExceeded(),
    )
    def test_batch_upgrade_timeout(self, *args):
        env = self._create_upgrade_env()
        # will be executed synchronously due to CELERY_IS_EAGER = True
        tasks.batch_upgrade_operation.delay(
            build_id=env['build2'].pk, firmwareless=False
        )
        self.assertEqual(BatchUpgradeOperation.objects.count(), 1)
        batch = BatchUpgradeOperation.objects.first()
        self.assertEqual(batch.status, 'failed')
