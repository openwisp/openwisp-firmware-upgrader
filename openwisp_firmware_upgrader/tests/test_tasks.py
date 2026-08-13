from unittest import mock

from celery.exceptions import SoftTimeLimitExceeded
from django.test import TransactionTestCase

from openwisp_utils.tests import capture_any_output

from .. import tasks
from ..swapper import load_model
from .base import TestUpgraderMixin

BatchUpgradeOperation = load_model("BatchUpgradeOperation")
DeviceFirmware = load_model("DeviceFirmware")
UpgradeOperation = load_model("UpgradeOperation")


class TestTasks(TestUpgraderMixin, TransactionTestCase):
    _mock_upgrade = "openwisp_firmware_upgrader.upgraders.openwrt.OpenWrt.upgrade"
    _mock_connect = "openwisp_controller.connection.models.DeviceConnection.connect"

    @mock.patch(_mock_upgrade, side_effect=SoftTimeLimitExceeded())
    @mock.patch(
        "openwisp_firmware_upgrader.base.models.AbstractUpgradeOperation.upgrade",
        side_effect=SoftTimeLimitExceeded(),
    )
    @capture_any_output()
    def test_upgrade_firmware_timeout(self, *args):
        with mock.patch(self._mock_connect, return_value=True):
            device_fw = self._create_device_firmware(upgrade=True)
            self.assertEqual(UpgradeOperation.objects.count(), 1)
            uo = device_fw.image.upgradeoperation_set.first()
            self.assertEqual(uo.status, "failed")
            self.assertIn("Operation timed out.", uo.log)

    @mock.patch(_mock_upgrade, return_value=True)
    @mock.patch(
        "openwisp_firmware_upgrader.base.models.AbstractDeviceFirmware.create_upgrade_operation",
        side_effect=SoftTimeLimitExceeded(),
    )
    @capture_any_output()
    def test_batch_upgrade_timeout(self, *args):
        with mock.patch(self._mock_connect, return_value=True):
            env = self._create_upgrade_env()
            batch = BatchUpgradeOperation.objects.create(build=env["build2"])
            # will be executed synchronously due to CELERY_IS_EAGER = True
            tasks.batch_upgrade_operation.delay(batch_id=batch.pk, firmwareless=False)
            self.assertEqual(BatchUpgradeOperation.objects.count(), 1)
            batch = BatchUpgradeOperation.objects.first()
            self.assertEqual(batch.status, "failed")

    @mock.patch(_mock_upgrade, return_value=True)
    @mock.patch("logging.Logger.warning")
    def test_upgrade_firmware_resilience(self, mocked_logger, *args):
        with mock.patch(self._mock_connect, return_value=True):
            upgrade_op_id = UpgradeOperation().id
            tasks.upgrade_firmware.run(upgrade_op_id)
            mocked_logger.assert_called_with(
                f"The UpgradeOperation object with id {upgrade_op_id} has been deleted"
            )

    @mock.patch(_mock_upgrade, return_value=True)
    @mock.patch("logging.Logger.warning")
    def test_batch_upgrade_operation_resilience(self, mocked_logger, *args):
        with mock.patch(self._mock_connect, return_value=True):
            batch_id = BatchUpgradeOperation().id
            tasks.batch_upgrade_operation.run(batch_id=batch_id, firmwareless=False)
            mocked_logger.assert_called_with(
                f"The BatchUpgradeOperation object with id {batch_id} has been deleted"
            )

    def test_create_all_device_firmwares_excludes_deactivated_and_disabled_org(self):
        org = self._get_org()
        category = self._get_category(organization=org)
        build = self._create_build(category=category, version="0.1", os="TestOS")
        image = self._create_firmware_image(build=build)

        with self.subTest("deactivated device"):
            device = self._create_device(
                name="deactivated-device",
                organization=org,
                os="TestOS",
                model=image.boards[0],
                mac_address="00:11:22:33:77:01",
            )
            device.deactivate()
            tasks.create_all_device_firmwares.run(image.pk)
            self.assertEqual(DeviceFirmware.objects.filter(device=device).count(), 0)

        with self.subTest("disabled organization device"):
            disabled_org = self._create_org(name="disabled-org")
            device = self._create_device(
                name="disabled-org-device",
                organization=disabled_org,
                os="TestOS",
                model=image.boards[0],
                mac_address="00:11:22:33:77:02",
            )
            disabled_org.is_active = False
            disabled_org.save(update_fields=["is_active"])
            tasks.create_all_device_firmwares.run(image.pk)
            self.assertEqual(DeviceFirmware.objects.filter(device=device).count(), 0)

    @mock.patch("openwisp_firmware_upgrader.tasks.create_device_firmware.delay")
    def test_create_device_firmware_not_queued_for_deactivated_or_disabled_org(
        self, mocked_delay
    ):
        org = self._get_org()
        category = self._get_category(organization=org)
        build = self._create_build(category=category, version="0.1", os="TestOS")
        image = self._create_firmware_image(build=build)
        credentials = self._create_credentials(organization=None, auto_add=False)

        with self.subTest("deactivated device"):
            mocked_delay.reset_mock()
            device = self._create_device(
                name="deactivated-device",
                organization=org,
                os="TestOS",
                model=image.boards[0],
                mac_address="00:11:22:33:88:01",
            )
            self._create_config(device=device)
            device.deactivate()
            self._create_device_connection(device=device, credentials=credentials)
            mocked_delay.assert_not_called()
            self.assertEqual(DeviceFirmware.objects.filter(device=device).count(), 0)

        with self.subTest("disabled organization device"):
            mocked_delay.reset_mock()
            disabled_org = self._create_org(name="disabled-org")
            device = self._create_device(
                name="disabled-org-device",
                organization=disabled_org,
                os="TestOS",
                model=image.boards[0],
                mac_address="00:11:22:33:88:02",
            )
            self._create_config(device=device)
            disabled_org.is_active = False
            disabled_org.save(update_fields=["is_active"])
            self._create_device_connection(device=device, credentials=credentials)
            mocked_delay.assert_not_called()
            self.assertEqual(DeviceFirmware.objects.filter(device=device).count(), 0)
