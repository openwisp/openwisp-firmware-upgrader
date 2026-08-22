from unittest import mock

import swapper
from celery.exceptions import SoftTimeLimitExceeded
from django.test import TransactionTestCase

from openwisp_utils.tests import capture_any_output

from .. import tasks
from ..swapper import load_model
from .base import TestUpgraderMixin

BatchUpgradeOperation = load_model("BatchUpgradeOperation")
DeviceFirmware = load_model("DeviceFirmware")
FirmwareImage = load_model("FirmwareImage")
UpgradeOperation = load_model("UpgradeOperation")
Device = swapper.load_model("config", "Device")


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

    def test_create_all_device_firmwares_filters_incompatible_devices(self):
        org1 = self._get_org()
        org2 = self._create_org(name="Other Org", slug="other-org")
        os_version = "OpenWrt 23.05.0"
        build = self._create_build(organization=org1, os=os_version)
        fw_image = self._create_firmware_image(
            build=build, type=self.TPLINK_4300_IMAGE
        )
        supported_board = fw_image.boards[0]

        # 1. Eligible device: matching OS, matching model, no existing firmware, active, same org
        d_eligible = self._create_device(
            name="Eligible Device",
            mac_address="00:11:22:33:44:01",
            organization=org1,
            model=supported_board,
            os=os_version,
        )
        # 2. Ineligible: different hardware model sharing same OS
        d_different_model = self._create_device(
            name="Different Model Device",
            mac_address="00:11:22:33:44:02",
            organization=org1,
            model="YunCore XD3200",
            os=os_version,
        )
        # 3. Ineligible: different organization
        d_different_org = self._create_device(
            name="Different Org Device",
            mac_address="00:11:22:33:44:03",
            organization=org2,
            model=supported_board,
            os=os_version,
        )
        # 4. Ineligible: deactivated device
        d_deactivated = self._create_device(
            name="Deactivated Device",
            mac_address="00:11:22:33:44:04",
            organization=org1,
            model=supported_board,
            os=os_version,
        )
        d_deactivated.deactivate()
        # 5. Ineligible: device already has a DeviceFirmware
        d_existing_fw = self._create_device(
            name="Existing FW Device",
            mac_address="00:11:22:33:44:05",
            organization=org1,
            model=supported_board,
            os=os_version,
        )
        old_build = self._create_build(
            organization=org1, version="0.0.1", os="OpenWrt 21.02"
        )
        old_image = self._create_firmware_image(
            build=old_build, type=self.TPLINK_4300_IMAGE
        )
        existing_df = DeviceFirmware.objects.create(
            device=d_existing_fw, image=old_image, installed=True
        )

        with mock.patch.object(
            DeviceFirmware, "create_for_device", wraps=DeviceFirmware.create_for_device
        ) as mock_create:
            tasks.create_all_device_firmwares.run(fw_image.pk)
            # Ensure create_for_device was only called for the single eligible device
            self.assertEqual(mock_create.call_count, 1)
            self.assertEqual(mock_create.call_args[0][0], d_eligible)

        d_eligible.refresh_from_db()
        self.assertTrue(hasattr(d_eligible, "devicefirmware"))
        self.assertEqual(d_eligible.devicefirmware.image, fw_image)
        self.assertEqual(d_eligible.devicefirmware.installed, True)

        d_existing_fw.refresh_from_db()
        self.assertEqual(d_existing_fw.devicefirmware.pk, existing_df.pk)
        self.assertEqual(d_existing_fw.devicefirmware.image, old_image)

        for dev in [d_different_model, d_different_org, d_deactivated]:
            dev.refresh_from_db()
            self.assertFalse(hasattr(dev, "devicefirmware"))

    def test_create_all_device_firmwares_shared_category(self):
        org1 = self._get_org()
        org2 = self._create_org(name="Org 2", slug="org-2")
        os_version = "OpenWrt 23.05.1"
        shared_category = self._create_category(
            name="Shared Category", organization=None
        )
        build = self._create_build(category=shared_category, os=os_version)
        fw_image = self._create_firmware_image(
            build=build, type=self.TPLINK_4300_IMAGE
        )
        supported_board = fw_image.boards[0]

        d_org1 = self._create_device(
            name="Org1 Device",
            mac_address="00:11:22:33:44:11",
            organization=org1,
            model=supported_board,
            os=os_version,
        )
        d_org2 = self._create_device(
            name="Org2 Device",
            mac_address="00:11:22:33:44:12",
            organization=org2,
            model=supported_board,
            os=os_version,
        )

        tasks.create_all_device_firmwares.run(fw_image.pk)

        d_org1.refresh_from_db()
        d_org2.refresh_from_db()
        self.assertEqual(d_org1.devicefirmware.image, fw_image)
        self.assertEqual(d_org2.devicefirmware.image, fw_image)

    def test_create_all_device_firmwares_no_build_os(self):
        org = self._get_org()
        build = self._create_build(organization=org, os=None)
        fw_image = self._create_firmware_image(
            build=build, type=self.TPLINK_4300_IMAGE
        )
        d = self._create_device(
            name="Device",
            organization=org,
            model=fw_image.boards[0],
            os="OpenWrt 23.05",
        )

        with mock.patch.object(DeviceFirmware, "create_for_device") as mock_create:
            tasks.create_all_device_firmwares.run(fw_image.pk)
            mock_create.assert_not_called()

        d.refresh_from_db()
        self.assertFalse(hasattr(d, "devicefirmware"))
