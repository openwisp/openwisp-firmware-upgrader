import io
import uuid
from contextlib import redirect_stdout
from unittest import mock
from unittest.mock import MagicMock, patch

import swapper
from celery.exceptions import Retry
from django.core.exceptions import ValidationError
from django.test import TestCase, TransactionTestCase

from openwisp_utils.tests import capture_any_output

from .. import settings as app_settings
from ..hardware import FIRMWARE_IMAGE_MAP, REVERSE_FIRMWARE_IMAGE_MAP
from ..swapper import load_model
from ..tasks import upgrade_firmware
from .base import TestUpgraderMixin

Group = swapper.load_model("openwisp_users", "Group")
BatchUpgradeOperation = load_model("BatchUpgradeOperation")
Build = load_model("Build")
Category = load_model("Category")
DeviceFirmware = load_model("DeviceFirmware")
FirmwareImage = load_model("FirmwareImage")
UpgradeOperation = load_model("UpgradeOperation")
DeviceConnection = swapper.load_model("connection", "DeviceConnection")
Credentials = swapper.load_model("connection", "Credentials")
Device = swapper.load_model("config", "Device")
Location = swapper.load_model("geo", "Location")
DeviceLocation = swapper.load_model("geo", "DeviceLocation")


class TestModels(TestUpgraderMixin, TestCase):
    app_label = "openwisp_firmware_upgrader"
    os = "OpenWrt 19.07-SNAPSHOT r11061-6ffd4d8a4d"
    image_type = REVERSE_FIRMWARE_IMAGE_MAP["YunCore XD3200"]

    def test_category_str(self):
        c = Category(name="WiFi Hotspot")
        self.assertEqual(str(c), c.name)

    def test_build_str(self):
        c = self._create_category()
        b = Build(category=c, version="0.1")
        self.assertIn(c.name, str(b))
        self.assertIn(b.version, str(b))

    def test_build_str_no_category(self):
        b = Build()
        self.assertIsNotNone(str(b))

    def test_build_clean(self):
        org = self._get_org()
        cat1 = self._get_category(organization=org)
        cat2 = self._create_category(name="New category", organization=org)
        b1 = self._create_build(organization=org, category=cat1, os=self.os)

        with self.subTest("validation error should be raised"):
            try:
                self._create_build(organization=org, category=cat2, os=self.os)
            except ValidationError as e:
                self.assertIn("os", e.message_dict)
            else:
                self.fail("ValidationError not raised")

        with self.subTest("1 build object expected"):
            self.assertEqual(Build.objects.count(), 1)

        with self.subTest("validating the same object again should work"):
            b1.full_clean()

        with self.subTest("validation error should be raised on empty category"):
            try:
                b2 = self._create_build(
                    os=self.os + "_2", version="0.2", organization=org
                )
                b2.category = None
                b2.full_clean()
            except ValidationError as e:
                self.assertIn("category", e.message_dict)
            else:
                self.fail("ValidationError not raised when build category is empty")

    def test_fw_str(self):
        fw = self._create_firmware_image()
        self.assertIn(str(fw.build), str(fw))
        self.assertIn(fw.build.category.name, str(fw))

    def test_fw_str_new(self):
        fw = FirmwareImage()
        self.assertIsNotNone(str(fw))

    def test_fw_auto_type(self):
        fw = self._create_firmware_image(type="")
        self.assertEqual(fw.type, self.TPLINK_4300_IMAGE)

    def test_device_firmware_multitenancy(self):
        device_fw = self._create_device_firmware()
        org2 = self._create_org(name="org2")
        shared_image = self._create_firmware_image(organization=None)
        org2_image = self._create_firmware_image(organization=org2)

        with self.subTest("Test with firmware from another organization"):
            device_fw.image = org2_image
            with self.assertRaises(ValidationError) as context:
                device_fw.full_clean()
            self.assertEqual(
                context.exception.message_dict["image"][0],
                "The organization of the image doesn't match the organization of the device",
            )

        with self.subTest("Test with shared firmware"):
            device_fw.image = shared_image
            try:
                device_fw.full_clean()
                device_fw.save()
            except Exception as error:
                self.fail("Test failed with error: {}".format(error))

    def test_device_fw_image_changed(self, *args):
        with mock.patch(
            f"{self.app_label}.models.UpgradeOperation.upgrade", return_value=None
        ):
            device_fw = DeviceFirmware()
            self.assertIsNone(device_fw._old_image)
            # save
            device_fw = self._create_device_firmware(upgrade=False)
            self.assertEqual(device_fw._old_image, device_fw.image)
            self.assertEqual(UpgradeOperation.objects.count(), 0)
            # init
            device_fw = DeviceFirmware.objects.first()
            self.assertEqual(device_fw._old_image, device_fw.image)
            # change
            build2 = self._create_build(
                category=device_fw.image.build.category, version="0.2"
            )
            fw2 = self._create_firmware_image(build=build2, type=device_fw.image.type)
            old_image = device_fw.image
            device_fw.image = fw2
            self.assertNotEqual(device_fw._old_image, device_fw.image)
            self.assertEqual(device_fw._old_image, old_image)
            device_fw.full_clean()
            device_fw.save()
            self.assertEqual(UpgradeOperation.objects.count(), 1)
            self.assertEqual(BatchUpgradeOperation.objects.count(), 0)

    def test_device_fw_created(self, *args):
        with mock.patch(
            f"{self.app_label}.models.UpgradeOperation.upgrade", return_value=None
        ):
            self._create_device_firmware(upgrade=True)
            self.assertEqual(UpgradeOperation.objects.count(), 1)
            self.assertEqual(BatchUpgradeOperation.objects.count(), 0)

    def test_device_fw_image_saved_not_installed(self, *args):
        with mock.patch(
            f"{self.app_label}.models.UpgradeOperation.upgrade", return_value=None
        ):
            device_fw = DeviceFirmware()
            self.assertIsNone(device_fw._old_image)
            # save
            device_fw = self._create_device_firmware(upgrade=False, installed=False)
            self.assertEqual(device_fw._old_image, device_fw.image)
            self.assertEqual(UpgradeOperation.objects.count(), 0)
            device_fw.full_clean()
            device_fw.save()
            self.assertEqual(UpgradeOperation.objects.count(), 1)
            self.assertEqual(BatchUpgradeOperation.objects.count(), 0)

    def test_device_fw_no_connection(self):
        try:
            self._create_device_firmware(device_connection=False)
        except ValidationError as e:
            self.assertIn("related connection", str(e))
        else:
            self.fail("ValidationError not raised")

    def test_invalid_board(self):
        image = FIRMWARE_IMAGE_MAP[self.TPLINK_4300_IMAGE]
        boards = image["boards"]
        del image["boards"]
        err = None
        try:
            self._create_firmware_image()
        except ValidationError as e:
            err = e
        image["boards"] = boards
        if err:
            self.assertIn("type", err.message_dict)
            self.assertIn("not find boards", str(err))
        else:
            self.fail("ValidationError not raised")

    def test_custom_image_type_present(self):
        t = FirmwareImage._meta.get_field("type")
        custom_images = app_settings.CUSTOM_OPENWRT_IMAGES
        self.assertEqual(t.choices[0][0], custom_images[0][0])

    def test_device_firmware_image_invalid_model(self):
        device_fw = self._create_device_firmware()
        different_img = self._create_firmware_image(
            build=device_fw.image.build, type=self.TPLINK_4300_IL_IMAGE
        )
        try:
            device_fw.image = different_img
            device_fw.full_clean()
        except ValidationError as e:
            self.assertIn("model do not match", str(e))
        else:
            self.fail("ValidationError not raised")

    def test_upgrade_operation_invalid_upgrade_options(self):
        device_fw = self._create_device_firmware()
        uo = UpgradeOperation(
            device=device_fw.device,
            image=device_fw.image,
        )
        with self.subTest("Test using invalid options"):
            uo.upgrade_options = {"invalid": True}
            with self.assertRaises(ValidationError) as error:
                uo.full_clean()
            self.assertEqual(
                error.exception.message_dict["__all__"],
                ["The upgrade options are invalid"],
            )

        with self.subTest("Test using mutually exclusive options"):
            uo.upgrade_options = {"c": True, "n": True}
            with self.assertRaises(ValidationError) as error:
                uo.full_clean()
            self.assertEqual(
                error.exception.message_dict["upgrade_options"],
                ['The "-n" and "-c" options cannot be used together'],
            )

            uo.upgrade_options = {"o": True, "n": True}
            with self.assertRaises(ValidationError) as error:
                uo.full_clean()
            self.assertEqual(
                error.exception.message_dict["upgrade_options"],
                ['The "-n" and "-o" options cannot be used together'],
            )

    def test_upgrade_operation_log_line(self):
        device_fw = self._create_device_firmware()
        uo = UpgradeOperation(device=device_fw.device, image=device_fw.image)
        uo.log_line("line1", save=False)
        uo.log_line("line2", save=False)
        self.assertEqual(uo.log, "line1\nline2")
        try:
            uo.refresh_from_db()
        except UpgradeOperation.DoesNotExist:
            pass
        else:
            self.fail("item has been saved")

    def test_upgrade_operation_log_line_save(self):
        device_fw = self._create_device_firmware()
        uo = UpgradeOperation(device=device_fw.device, image=device_fw.image)
        uo.log_line("line1")
        uo.log_line("line2")
        uo.refresh_from_db()
        self.assertEqual(uo.log, "line1\nline2")

    def test_permissions(self):
        admin = Group.objects.get(name="Administrator")
        operator = Group.objects.get(name="Operator")

        admin_permissions = [
            p["codename"] for p in admin.permissions.values("codename")
        ]
        operator_permissions = [
            p["codename"] for p in operator.permissions.values("codename")
        ]

        operators_read_only_admins_manage = [
            "build",
            "devicefirmware",
            "firmwareimage",
            "batchupgradeoperation",
            "upgradeoperation",
        ]
        admins_can_manage = ["category"]
        manage_operations = ["add", "change", "delete"]

        for action in manage_operations:
            for model_name in admins_can_manage:
                codename = "{}_{}".format(action, model_name)
                self.assertIn(codename, admin_permissions)
                self.assertNotIn(codename, operator_permissions)

        for model_name in operators_read_only_admins_manage:
            codename = "view_{}".format(model_name)
            self.assertIn(codename, operator_permissions)

            for action in manage_operations:
                codename = "{}_{}".format(action, model_name)
                self.assertIn(codename, admin_permissions)

    @capture_any_output()
    def test_create_for_device_validation_error(self):
        device_fw = self._create_device_firmware()
        device_fw.image.build.os = device_fw.device.os
        device_fw.image.build.save()
        result = DeviceFirmware.create_for_device(device_fw.device)
        self.assertIsNone(result)

    def test_upgrade_operation_retention_on_image_delete(self):
        device_fw = self._create_device_firmware()
        uo = UpgradeOperation.objects.create(
            device=device_fw.device, image=device_fw.image
        )
        FirmwareImage.objects.get(pk=device_fw.image.pk).delete()
        self.assertEqual(UpgradeOperation.objects.get(pk=uo.pk).image, None)

    def test_delete_firmware_image_file(self):
        file_storage_backend = FirmwareImage.file.field.storage

        with self.subTest("Test deleting object deletes file"):
            image = self._create_firmware_image()
            file_name = image.file.name
            image.delete()
            self.assertEqual(file_storage_backend.exists(file_name), False)

        with self.subTest("Test deleting object with a deleted file"):
            image = self._create_firmware_image()
            file_name = image.file.name
            # Delete the file from the storage backend before
            # deleting the object
            file_storage_backend.delete(file_name)
            self.assertNotEqual(image.file, None)
            image.delete()

    @patch("django.db.transaction.on_commit")
    @patch.object(FirmwareImage, "objects")
    def test_schedule_firmware_file_deletion_with_files(
        self, mock_fw_image_manager, mock_on_commit
    ):
        mock_image1 = MagicMock()
        mock_image1.file.name = "build/123/image1.bin"
        mock_image2 = MagicMock()
        mock_image2.file.name = "build/123/image2.bin"
        mocked_qs_result = MagicMock()
        mocked_qs_result.iterator.return_value = [mock_image1, mock_image2]
        mock_fw_image_manager.filter.return_value = mocked_qs_result
        FirmwareImage.schedule_firmware_file_deletion(build__id=123)
        mock_fw_image_manager.filter.assert_called_once_with(build__id=123)
        mock_on_commit.assert_called_once()
        # The actual partial function call is complex to test directly,
        # but we can verify it was called with the right pattern
        call_args = mock_on_commit.call_args[0][0]
        self.assertIsNotNone(call_args)

    @patch("django.db.transaction.on_commit")
    @patch.object(FirmwareImage, "objects")
    def test_schedule_firmware_file_deletion_no_files(
        self, mock_fw_image_manager, mock_on_commit
    ):
        mocked_qs_result = MagicMock()
        mocked_qs_result.iterator.return_value = []
        mock_fw_image_manager.filter.return_value = mocked_qs_result
        FirmwareImage.schedule_firmware_file_deletion(build__id=123)
        mock_on_commit.assert_not_called()

    @patch("django.db.transaction.on_commit")
    @patch.object(FirmwareImage, "objects")
    def test_schedule_firmware_file_deletion_files_without_names(
        self, mock_fw_image_manager, mock_on_commit
    ):
        mock_image1 = MagicMock()
        mock_image1.file.name = "build/123/image1.bin"
        mock_image2 = MagicMock()
        mock_image2.file.name = None  # No file name
        mock_image3 = MagicMock()
        mock_image3.file.name = ""  # Empty file name
        mocked_qs_result = MagicMock()
        mocked_qs_result.iterator.return_value = [
            mock_image1,
            mock_image2,
            mock_image3,
        ]
        mock_fw_image_manager.filter.return_value = mocked_qs_result
        FirmwareImage.schedule_firmware_file_deletion(category__id=456)
        mock_fw_image_manager.filter.assert_called_once_with(category__id=456)
        # Should still call transaction.on_commit because image1 has a valid file name
        mock_on_commit.assert_called_once()

    @patch("openwisp_firmware_upgrader.base.models.logger")
    @patch.object(FirmwareImage.file.field, "storage")
    def test_remove_file_success(self, mock_storage, mock_logger):
        mock_storage.listdir.return_value = ([], [])  # Empty directory
        result = FirmwareImage._remove_file("build/123/firmware.bin")
        self.assertTrue(result)
        mock_storage.delete.assert_any_call("build/123/firmware.bin")
        mock_storage.delete.assert_any_call("build/123")
        mock_logger.info.assert_any_call(
            "Deleted firmware file: %s", "build/123/firmware.bin"
        )
        mock_logger.info.assert_any_call("Deleted empty directory: %s", "build/123")
        self.assertEqual(mock_storage.delete.call_count, 2)

    @patch("openwisp_firmware_upgrader.base.models.logger")
    @patch.object(FirmwareImage.file.field, "storage")
    def test_remove_file_non_empty_directory(self, mock_storage, mock_logger):
        mock_storage.listdir.return_value = (["subdir"], ["other_file.bin"])
        result = FirmwareImage._remove_file("build/123/firmware.bin")
        self.assertTrue(result)
        mock_storage.delete.assert_called_once_with("build/123/firmware.bin")
        mock_logger.info.assert_called_once_with(
            "Deleted firmware file: %s", "build/123/firmware.bin"
        )
        mock_logger.debug.assert_called_once_with(
            "Directory %s is not empty, skipping deletion", "build/123"
        )

    @patch("openwisp_firmware_upgrader.base.models.logger")
    @patch.object(FirmwareImage.file.field, "storage")
    def test_remove_file_file_deletion_failure(self, mock_storage, mock_logger):
        mock_storage.delete.side_effect = Exception("Storage error")
        result = FirmwareImage._remove_file("build/123/firmware.bin")
        self.assertFalse(result)
        mock_storage.delete.assert_called_once_with("build/123/firmware.bin")
        mock_logger.error.assert_called_once_with(
            "Error deleting firmware file %s: %s",
            "build/123/firmware.bin",
            "Storage error",
        )
        mock_logger.info.assert_not_called()

    @patch("openwisp_firmware_upgrader.base.models.logger")
    @patch.object(FirmwareImage.file.field, "storage")
    def test_remove_file_directory_listing_failure(self, mock_storage, mock_logger):
        mock_storage.listdir.side_effect = Exception("Directory access error")
        result = FirmwareImage._remove_file("build/123/firmware.bin")
        self.assertTrue(result)  # File deletion succeeded, directory cleanup failed
        mock_storage.delete.assert_called_once_with("build/123/firmware.bin")
        mock_logger.info.assert_called_once_with(
            "Deleted firmware file: %s", "build/123/firmware.bin"
        )
        mock_logger.error.assert_called_once_with(
            "Could not delete directory %s: %s", "build/123", "Directory access error"
        )

    @patch("openwisp_firmware_upgrader.base.models.logger")
    @patch.object(FirmwareImage.file.field, "storage")
    def test_remove_file_directory_not_found(self, mock_storage, mock_logger):
        mock_storage.listdir.side_effect = FileNotFoundError("Directory not found")
        result = FirmwareImage._remove_file("build/123/firmware.bin")
        self.assertTrue(result)  # File deletion succeeded
        mock_storage.delete.assert_called_once_with("build/123/firmware.bin")
        mock_logger.info.assert_called_once_with(
            "Deleted firmware file: %s", "build/123/firmware.bin"
        )
        # Expecting debug, not error
        mock_logger.debug.assert_called_once_with(
            "Directory %s already removed", "build/123"
        )
        mock_logger.error.assert_not_called()

    @patch("openwisp_firmware_upgrader.base.models.logger")
    @patch.object(FirmwareImage.file.field, "storage")
    def test_remove_file_directory_deletion_failure(self, mock_storage, mock_logger):
        mock_storage.listdir.return_value = ([], [])  # Empty directory
        mock_storage.delete.side_effect = [None, Exception("Directory deletion error")]
        result = FirmwareImage._remove_file("build/123/firmware.bin")
        self.assertTrue(result)  # File deletion succeeded, directory cleanup failed
        mock_logger.info.assert_called_once_with(
            "Deleted firmware file: %s", "build/123/firmware.bin"
        )
        mock_logger.error.assert_called_once_with(
            "Could not delete directory %s: %s", "build/123", "Directory deletion error"
        )

    @patch("openwisp_firmware_upgrader.base.models.logger")
    @patch.object(FirmwareImage.file.field, "storage")
    def test_remove_file_root_directory(self, mock_storage, mock_logger):
        result = FirmwareImage._remove_file("firmware.bin")
        self.assertTrue(result)
        mock_storage.delete.assert_called_once_with("firmware.bin")
        # Expecting directory cleanup is skipped
        mock_storage.listdir.assert_not_called()
        mock_logger.info.assert_called_once_with(
            "Deleted firmware file: %s", "firmware.bin"
        )


class TestModelsTransaction(TestUpgraderMixin, TransactionTestCase):
    _mock_updrade = "openwisp_firmware_upgrader.upgraders.openwrt.OpenWrt.upgrade"
    _mock_connect = "openwisp_controller.connection.models.DeviceConnection.connect"
    os = TestModels.os
    image_type = TestModels.image_type

    @mock.patch(_mock_updrade, return_value=True)
    @mock.patch(_mock_connect, return_value=True)
    def test_dry_run(self, *args):
        env = self._create_upgrade_env()
        # check pending upgrades
        result = BatchUpgradeOperation.dry_run(build=env["build1"])
        self.assertEqual(
            list(result["device_firmwares"]),
            list(DeviceFirmware.objects.all().order_by("-created")),
        )
        self.assertEqual(list(result["devices"]), [])
        # upgrade devices
        env["build1"].batch_upgrade(firmwareless=True)
        # check pending upgrades again
        result = BatchUpgradeOperation.dry_run(build=env["build1"])
        self.assertEqual(list(result["device_firmwares"]), [])
        self.assertEqual(list(result["devices"]), [])

    @mock.patch(_mock_updrade, return_value=True)
    @mock.patch(_mock_connect, return_value=True)
    def test_upgrade_related_devices(self, *args):
        env = self._create_upgrade_env()
        # check everything is as expected
        self.assertEqual(UpgradeOperation.objects.count(), 0)
        self.assertEqual(env["d1"].devicefirmware.image, env["image1a"])
        self.assertEqual(env["d2"].devicefirmware.image, env["image1b"])
        # upgrade all related
        env["build2"].batch_upgrade(firmwareless=False)
        # ensure image is changed
        env["d1"].devicefirmware.refresh_from_db()
        env["d2"].devicefirmware.refresh_from_db()
        self.assertEqual(env["d1"].devicefirmware.image, env["image2a"])
        self.assertEqual(env["d2"].devicefirmware.image, env["image2b"])
        # ensure upgrade operation objects have been created
        self.assertEqual(UpgradeOperation.objects.count(), 2)
        batch_qs = BatchUpgradeOperation.objects.all()
        self.assertEqual(batch_qs.count(), 1)
        batch = batch_qs.first()
        self.assertEqual(batch.upgradeoperation_set.count(), 2)
        self.assertEqual(batch.build, env["build2"])
        self.assertEqual(batch.status, "success")

    @mock.patch(_mock_updrade, return_value=True)
    @mock.patch(_mock_connect, return_value=True)
    def test_upgrade_firmwareless_devices(self, *args):
        env = self._create_upgrade_env(device_firmware=False)
        # check everything is as expected
        self.assertEqual(UpgradeOperation.objects.count(), 0)
        self.assertFalse(hasattr(env["d1"], "devicefirmware"))
        self.assertFalse(hasattr(env["d2"], "devicefirmware"))
        # upgrade all related
        env["build2"].batch_upgrade(firmwareless=True)
        env["d1"].refresh_from_db()
        env["d2"].refresh_from_db()
        self.assertEqual(env["d1"].devicefirmware.image, env["image2a"])
        self.assertEqual(env["d2"].devicefirmware.image, env["image2b"])
        # ensure upgrade operation objects have been created
        self.assertEqual(UpgradeOperation.objects.count(), 2)
        batch_qs = BatchUpgradeOperation.objects.all()
        self.assertEqual(batch_qs.count(), 1)
        batch = batch_qs.first()
        self.assertEqual(batch.upgradeoperation_set.count(), 2)
        self.assertEqual(batch.build, env["build2"])
        self.assertEqual(batch.status, "success")

    @mock.patch.object(upgrade_firmware, "max_retries", 0)
    def test_batch_upgrade_failure(self):
        env = self._create_upgrade_env()
        with redirect_stdout(io.StringIO()):
            env["build2"].batch_upgrade(firmwareless=False)
        batch = BatchUpgradeOperation.objects.first()
        self.assertEqual(batch.status, "failed")
        self.assertEqual(BatchUpgradeOperation.objects.count(), 1)

    @mock.patch(_mock_updrade, return_value=True)
    @mock.patch(_mock_connect, return_value=True)
    def test_upgrade_related_devices_existing_fw(self, *args):
        env = self._create_upgrade_env()
        self.assertEqual(UpgradeOperation.objects.count(), 0)
        self.assertEqual(env["d1"].devicefirmware.image, env["image1a"])
        self.assertEqual(env["d2"].devicefirmware.image, env["image1b"])
        env["d1"].devicefirmware.installed = False
        env["d1"].devicefirmware.save(upgrade=False)
        env["d2"].devicefirmware.installed = False
        env["d2"].devicefirmware.save(upgrade=False)
        env["build1"].batch_upgrade(firmwareless=False)
        env["d1"].devicefirmware.refresh_from_db()
        env["d2"].devicefirmware.refresh_from_db()
        self.assertEqual(env["d1"].devicefirmware.image, env["image1a"])
        self.assertEqual(env["d2"].devicefirmware.image, env["image1b"])
        self.assertEqual(UpgradeOperation.objects.count(), 2)
        batch_qs = BatchUpgradeOperation.objects.all()
        self.assertEqual(batch_qs.count(), 1)
        batch = batch_qs.first()
        self.assertEqual(batch.upgradeoperation_set.count(), 2)
        self.assertEqual(batch.build, env["build1"])
        self.assertEqual(batch.status, "success")

    def test_upgrade_retried(self):
        env = self._create_upgrade_env()
        try:
            with redirect_stdout(io.StringIO()):
                env["build2"].batch_upgrade(firmwareless=False)
        except Retry:
            pass
        except Exception as e:
            self.fail(f"Expected retry, got {e.__class__} instead")
        else:
            self.fail("Retry exception not raised")
        self.assertEqual(BatchUpgradeOperation.objects.count(), 1)
        batch = BatchUpgradeOperation.objects.first()
        self.assertEqual(batch.status, "in-progress")

    @mock.patch(_mock_updrade, return_value=True)
    @mock.patch(_mock_connect, return_value=True)
    def test_batch_upgrade_with_group_filtering(self, *args):
        """Test complete batch upgrade workflow with group filtering."""
        UpgradeOperation.objects.all().delete()

        org = self._get_org()
        category = self._create_category(organization=org)

        build1 = self._create_build(category=category, version="1.0")
        build2 = self._create_build(category=category, version="2.0")

        image1 = self._create_firmware_image(build=build1)
        image2 = self._create_firmware_image(build=build2)

        group1 = self._create_device_group(name="Group 1", organization=org)
        group2 = self._create_device_group(name="Group 2", organization=org)

        device1 = self._create_device(
            name="Device1",
            organization=org,
            group=group1,
            model=image1.boards[0],
            mac_address="00:11:22:33:55:31",
        )
        device2 = self._create_device(
            name="Device2",
            organization=org,
            group=group2,
            model=image1.boards[0],
            mac_address="00:11:22:33:55:32",
        )
        device3 = self._create_device(
            name="Device3",
            organization=org,
            group=None,
            model=image1.boards[0],
            mac_address="00:11:22:33:55:33",
        )

        # Create configs and connections
        self._create_config(device=device1)
        self._create_config(device=device2)
        self._create_config(device=device3)

        unique_id = str(uuid.uuid4())[:8]
        credentials = self._create_credentials(
            name=f"test-creds-{unique_id}", organization=None, auto_add=True
        )

        for device in [device1, device2, device3]:
            if not DeviceConnection.objects.filter(
                device=device, credentials=credentials
            ).exists():
                self._create_device_connection(device=device, credentials=credentials)

        with mock.patch(
            "openwisp_firmware_upgrader.base.models.AbstractDeviceFirmware.create_upgrade_operation"
        ):
            DeviceFirmware.objects.create(device=device1, image=image1, installed=True)
            DeviceFirmware.objects.create(device=device2, image=image1, installed=True)
            DeviceFirmware.objects.create(device=device3, image=image1, installed=True)

        # Create firmwareless device in group1
        device4 = self._create_device(
            name="Device4",
            organization=org,
            group=group1,
            model=image2.boards[0],
            mac_address="00:11:22:33:55:34",
        )
        self._create_config(device=device4)
        if not DeviceConnection.objects.filter(
            device=device4, credentials=credentials
        ).exists():
            self._create_device_connection(device=device4, credentials=credentials)

        # Test batch upgrade with group1 filter
        self.assertEqual(UpgradeOperation.objects.count(), 0)
        batch = build2.batch_upgrade(firmwareless=True, group=group1)

        self.assertEqual(batch.group, group1)

        upgrade_ops = UpgradeOperation.objects.all()
        upgraded_devices = [op.device.name for op in upgrade_ops]

        self.assertIn("Device1", upgraded_devices)
        self.assertIn("Device4", upgraded_devices)
        self.assertNotIn("Device2", upgraded_devices)
        self.assertNotIn("Device3", upgraded_devices)

        self.assertEqual(len(upgrade_ops), 2)

        batch.refresh_from_db()
        self.assertEqual(batch.status, "success")

    @mock.patch(_mock_updrade, return_value=True)
    @mock.patch(_mock_connect, return_value=True)
    def test_batch_upgrade_with_location_filtering(self, *args):
        """Test complete batch upgrade workflow with location filtering."""
        UpgradeOperation.objects.all().delete()

        org = self._get_org()
        category = self._create_category(organization=org)

        build1 = self._create_build(category=category, version="1.0")
        build2 = self._create_build(category=category, version="2.0")

        image1 = self._create_firmware_image(build=build1)
        image2 = self._create_firmware_image(build=build2)

        # Create locations
        location1 = Location.objects.create(
            name="Office Building A", address="123 Main St", organization=org
        )
        location2 = Location.objects.create(
            name="Office Building B", address="456 Oak Ave", organization=org
        )

        # Create devices
        device1 = self._create_device(
            name="Device1",
            organization=org,
            model=image1.boards[0],
            mac_address="00:11:22:33:55:41",
        )
        device2 = self._create_device(
            name="Device2",
            organization=org,
            model=image1.boards[0],
            mac_address="00:11:22:33:55:42",
        )
        device3 = self._create_device(
            name="Device3",
            organization=org,
            model=image1.boards[0],
            mac_address="00:11:22:33:55:43",
        )

        # Create device locations
        DeviceLocation.objects.create(content_object=device1, location=location1)
        DeviceLocation.objects.create(content_object=device2, location=location2)
        # device3 has no location

        # Create configs and connections
        self._create_config(device=device1)
        self._create_config(device=device2)
        self._create_config(device=device3)

        unique_id = str(uuid.uuid4())[:8]
        credentials = self._create_credentials(
            name=f"test-creds-{unique_id}", organization=None, auto_add=True
        )

        for device in [device1, device2, device3]:
            if not DeviceConnection.objects.filter(
                device=device, credentials=credentials
            ).exists():
                self._create_device_connection(device=device, credentials=credentials)

        # Create device firmware objects
        with mock.patch(
            "openwisp_firmware_upgrader.base.models.AbstractDeviceFirmware.create_upgrade_operation"
        ):
            DeviceFirmware.objects.create(device=device1, image=image1, installed=True)
            DeviceFirmware.objects.create(device=device2, image=image1, installed=True)
            DeviceFirmware.objects.create(device=device3, image=image1, installed=True)

        # Create firmwareless device at location1
        device4 = self._create_device(
            name="Device4",
            organization=org,
            model=image2.boards[0],
            mac_address="00:11:22:33:55:44",
        )
        DeviceLocation.objects.create(content_object=device4, location=location1)
        self._create_config(device=device4)
        if not DeviceConnection.objects.filter(
            device=device4, credentials=credentials
        ).exists():
            self._create_device_connection(device=device4, credentials=credentials)

        # Test batch upgrade with location1 filter
        self.assertEqual(UpgradeOperation.objects.count(), 0)
        batch = build2.batch_upgrade(firmwareless=True, location=location1)

        self.assertEqual(batch.location, location1)

        upgrade_ops = UpgradeOperation.objects.all()
        upgraded_devices = [op.device.name for op in upgrade_ops]

        # Only devices at location1 should be upgraded
        self.assertIn("Device1", upgraded_devices)  # at location1
        self.assertIn("Device4", upgraded_devices)  # at location1 (firmwareless)
        self.assertNotIn("Device2", upgraded_devices)  # at location2
        self.assertNotIn("Device3", upgraded_devices)  # no location

        self.assertEqual(len(upgrade_ops), 2)

        batch.refresh_from_db()
        self.assertEqual(batch.status, "success")

    @mock.patch(_mock_updrade, return_value=True)
    @mock.patch(_mock_connect, return_value=True)
    def test_batch_upgrade_with_group_and_location_filtering(self, *args):
        """Test batch upgrade with both group and location filtering."""
        UpgradeOperation.objects.all().delete()

        org = self._get_org()
        category = self._create_category(organization=org)
        build2 = self._create_build(category=category, version="2.0")
        image2 = self._create_firmware_image(build=build2)

        # Create group and location
        group1 = self._create_device_group(name="Group 1", organization=org)
        location1 = Location.objects.create(
            name="Office Building A", address="123 Main St", organization=org
        )

        # Create devices
        device1 = self._create_device(
            name="Device1-Group1-Loc1",
            organization=org,
            group=group1,
            model=image2.boards[0],
            mac_address="00:11:22:33:55:51",
        )
        device2 = self._create_device(
            name="Device2-Group1-NoLoc",
            organization=org,
            group=group1,
            model=image2.boards[0],
            mac_address="00:11:22:33:55:52",
        )
        device3 = self._create_device(
            name="Device3-NoGroup-Loc1",
            organization=org,
            group=None,
            model=image2.boards[0],
            mac_address="00:11:22:33:55:53",
        )

        # Set locations
        DeviceLocation.objects.create(content_object=device1, location=location1)
        DeviceLocation.objects.create(content_object=device3, location=location1)
        # device2 has no location

        # Create configs and connections
        unique_id = str(uuid.uuid4())[:8]
        credentials = self._create_credentials(
            name=f"test-creds-{unique_id}", organization=None, auto_add=True
        )
        for device in [device1, device2, device3]:
            self._create_config(device=device)
            if not DeviceConnection.objects.filter(
                device=device, credentials=credentials
            ).exists():
                self._create_device_connection(device=device, credentials=credentials)

        # Test batch upgrade with both group1 and location1 filters
        batch = build2.batch_upgrade(
            firmwareless=True, group=group1, location=location1
        )

        self.assertEqual(batch.group, group1)
        self.assertEqual(batch.location, location1)

        upgrade_ops = UpgradeOperation.objects.all()
        upgraded_devices = [op.device.name for op in upgrade_ops]

        # Only device1 should be upgraded (in group1 AND at location1)
        self.assertIn("Device1-Group1-Loc1", upgraded_devices)
        self.assertNotIn("Device2-Group1-NoLoc", upgraded_devices)  # wrong location
        self.assertNotIn("Device3-NoGroup-Loc1", upgraded_devices)  # wrong group

        self.assertEqual(len(upgrade_ops), 1)

        batch.refresh_from_db()
        self.assertEqual(batch.status, "success")

    def test_batch_upgrade_operation_location_validation(self):
        """Test location organization validation in BatchUpgradeOperation."""
        org1 = self._create_org(name="Org1")
        org2 = self._create_org(name="Org2")

        category1 = self._create_category(organization=org1)
        build1 = self._create_build(category=category1)

        location2 = Location.objects.create(
            name="Wrong Org Location", address="456 Wrong St", organization=org2
        )

        # Should raise validation error for mismatched organizations
        batch = BatchUpgradeOperation(build=build1, location=location2)

        with self.assertRaises(ValidationError) as cm:
            batch.full_clean()

        self.assertIn("location", cm.exception.message_dict)
        self.assertIn("organization", str(cm.exception.message_dict["location"]))

    def test_batch_upgrade_operation_dry_run_with_location(self):
        """Test dry_run method with location filtering."""
        org = self._get_org()
        category = self._create_category(organization=org)
        build = self._create_build(category=category)
        image = self._create_firmware_image(build=build)

        # Create location
        location = Location.objects.create(
            name="Test Location", address="123 Test St", organization=org
        )

        # Create device
        device1 = self._create_device(
            name="Device1-WithLocation",
            organization=org,
            model=image.boards[0],
            mac_address="00:11:22:33:55:61",
        )

        device2 = self._create_device(
            name="Device2-WithLocation",
            organization=org,
            model=image.boards[0],
            mac_address="00:11:22:33:55:62",
        )

        # Set location for device1 only
        DeviceLocation.objects.create(content_object=device1, location=location)

        # Create configs and connections so devices can be upgraded
        self._create_config(device=device1)
        self._create_config(device=device2)
        credentials = self._create_credentials(
            name="test-dry-run-creds", organization=None, auto_add=True
        )
        if not DeviceConnection.objects.filter(
            device=device1, credentials=credentials
        ).exists():
            self._create_device_connection(device=device1, credentials=credentials)
        if not DeviceConnection.objects.filter(
            device=device2, credentials=credentials
        ).exists():
            self._create_device_connection(device=device2, credentials=credentials)

        # Create device firmware for device1 (device2 is firmwareless)
        with mock.patch(
            "openwisp_firmware_upgrader.base.models.AbstractDeviceFirmware.create_upgrade_operation"
        ):
            DeviceFirmware.objects.create(device=device1, image=image, installed=False)

        # Test dry_run with location filter
        result = BatchUpgradeOperation.dry_run(build=build, location=location)

        device_fw_devices = [df.device for df in result["device_firmwares"]]
        self.assertIn(device1, device_fw_devices)
        self.assertEqual(len(result["device_firmwares"]), 1)

        # Firmwareless devices with location should be included
        firmwareless_devices = list(result["devices"])
        self.assertEqual(len(firmwareless_devices), 0)  # device2 has no location

        # Test dry_run without location filter
        result_no_filter = BatchUpgradeOperation.dry_run(build=build)
        self.assertEqual(len(result_no_filter["device_firmwares"]), 1)  # device1
        self.assertEqual(len(result_no_filter["devices"]), 1)  # device2

    def test_batch_upgrade_no_devices_with_filters(self):
        """Test that batch_upgrade raises ValidationError when no devices match filters."""
        org = self._get_org()
        category = self._create_category(organization=org)
        build = self._create_build(category=category, version="no-devices-test")
        
        # Create location but no devices at this location
        location = Location.objects.create(
            name="Empty Location",
            address="456 Empty St",
            organization=org
        )
        
        # Create group but no devices in this group  
        group = self._create_device_group(name="Empty Group", organization=org)
        
        with self.subTest("Test location filter with no devices"):
            with self.assertRaises(ValidationError) as cm:
                build.batch_upgrade(firmwareless=True, location=location)
            self.assertIn("No devices found matching", str(cm.exception))
            
        with self.subTest("Test group filter with no devices"):
            with self.assertRaises(ValidationError) as cm:
                build.batch_upgrade(firmwareless=True, group=group)
            self.assertIn("No devices found matching", str(cm.exception))
            
        with self.subTest("Test combined filters with no devices"):
            with self.assertRaises(ValidationError) as cm:
                build.batch_upgrade(firmwareless=True, group=group, location=location)
            self.assertIn("No devices found matching", str(cm.exception))
            
        # Verify no BatchUpgradeOperation objects were created
        self.assertEqual(BatchUpgradeOperation.objects.count(), 0)

    def test_device_fw_not_created_on_device_connection_save(self):
        org = self._get_org()
        category = self._get_category(organization=org)
        build1 = self._create_build(category=category, version="0.1", os=self.os)
        image1a = self._create_firmware_image(build=build1, type=self.image_type)

        with self.subTest("Device doesn't define os"):
            d1 = self._create_device_with_connection(
                name="test-no-os",
                os="",
                model=image1a.boards[0],
                mac_address="00:11:22:33:99:01",
            )
            self.assertEqual(DeviceConnection.objects.count(), 1)
            self.assertEqual(Device.objects.count(), 1)
            self.assertEqual(DeviceFirmware.objects.count(), 0)
            d1.delete(check_deactivated=False)
            Credentials.objects.all().delete()

        with self.subTest("Device doesn't define model"):
            d1 = self._create_device_with_connection(
                name="test-no-model",
                os=self.os,
                model="",
                mac_address="00:11:22:33:99:02",
            )
            self.assertEqual(DeviceConnection.objects.count(), 1)
            self.assertEqual(Device.objects.count(), 1)
            self.assertEqual(DeviceFirmware.objects.count(), 0)
            d1.delete(check_deactivated=False)
            Credentials.objects.all().delete()

        build1.os = None
        build1.save()

        with self.subTest("Build doesn't define os"):
            d1 = self._create_device_with_connection(
                name="test-no-build-os",
                model=image1a.boards[0],
                os=self.os,
                mac_address="00:11:22:33:99:03",
            )
            self.assertEqual(DeviceConnection.objects.count(), 1)
            self.assertEqual(Device.objects.count(), 1)
            self.assertEqual(DeviceFirmware.objects.count(), 0)

    def test_device_fw_created_on_device_connection_save(self):
        self.assertEqual(DeviceFirmware.objects.count(), 0)
        self.assertEqual(Device.objects.count(), 0)
        org = self._get_org()
        category = self._get_category(organization=org)
        build1 = self._create_build(category=category, version="0.1", os=self.os)
        image1a = self._create_firmware_image(build=build1, type=self.image_type)
        self._create_device_with_connection(
            name="test-fw-created",
            os=self.os,
            model=image1a.boards[0],
            mac_address="00:11:22:33:99:10",
        )
        self.assertEqual(Device.objects.count(), 1)
        self.assertEqual(DeviceFirmware.objects.count(), 1)
        self.assertEqual(DeviceConnection.objects.count(), 1)

    def test_delete_firmware_image_file(self):
        file_storage_backend = FirmwareImage.file.field.storage

        with self.subTest("Test deleting object deletes file"):
            image = self._create_firmware_image()
            file_name = image.file.name
            image.delete()
            self.assertEqual(file_storage_backend.exists(file_name), False)

        with self.subTest("Test deleting object with a deleted file"):
            image = self._create_firmware_image()
            file_name = image.file.name
            # Delete the file from the storage backend before
            # deleting the object
            file_storage_backend.delete(file_name)
            self.assertNotEqual(image.file, None)
            image.delete()

    def test_batch_upgrade_operation_group_validation(self):
        """Test group validation in BatchUpgradeOperation."""
        org1 = self._get_org()
        org2 = self._create_org(name="Org 2", slug="org2")

        category = self._create_category(organization=org1)
        build = self._create_build(category=category)

        group_org1 = self._create_device_group(name="Group Org1", organization=org1)
        group_org2 = self._create_device_group(name="Group Org2", organization=org2)

        batch1 = BatchUpgradeOperation(build=build, group=group_org1)
        batch1.full_clean()

        batch2 = BatchUpgradeOperation(build=build, group=group_org2)
        with self.assertRaises(ValidationError) as cm:
            batch2.full_clean()
        self.assertIn("group", cm.exception.message_dict)
        self.assertIn(
            "organization of the group", str(cm.exception.message_dict["group"][0])
        )

        batch3 = BatchUpgradeOperation(build=build, group=None)
        batch3.full_clean()

    def test_batch_upgrade_operation_group_validation_shared_build(self):
        """Test group validation for shared builds (organization=None)."""
        category = self._create_category(organization=None)  # Shared category
        build = self._create_build(category=category)

        org1 = self._get_org()
        group = self._create_device_group(name="Any Group", organization=org1)

        batch = BatchUpgradeOperation(build=build, group=group)
        batch.full_clean()

    def test_batch_upgrade_dry_run_with_group_filtering(self):
        """Test dry_run method with group filtering."""
        org = self._get_org()
        category = self._create_category(organization=org)
        build = self._create_build(category=category)
        image = self._create_firmware_image(build=build)

        group1 = self._create_device_group(name="Group 1", organization=org)
        group2 = self._create_device_group(name="Group 2", organization=org)

        # Create devices in different groups
        device1 = self._create_device(
            name="Device1",
            organization=org,
            group=group1,
            model=image.boards[0],
            mac_address="00:11:22:33:55:01",
        )
        device2 = self._create_device(
            name="Device2",
            organization=org,
            group=group2,
            model=image.boards[0],
            mac_address="00:11:22:33:55:02",
        )
        device3 = self._create_device(
            name="Device3",
            organization=org,
            group=None,
            model=image.boards[0],
            mac_address="00:11:22:33:55:03",
        )  # No group

        self._create_config(device=device1)
        self._create_config(device=device2)
        self._create_config(device=device3)

        unique_id = str(uuid.uuid4())[:8]
        credentials = self._create_credentials(
            name=f"test-creds-{unique_id}", organization=None, auto_add=True
        )

        for device in [device1, device2, device3]:
            if not DeviceConnection.objects.filter(
                device=device, credentials=credentials
            ).exists():
                self._create_device_connection(device=device, credentials=credentials)

        result = BatchUpgradeOperation.dry_run(build=build)
        device_names = [d.name for d in result["devices"]]
        self.assertIn("Device1", device_names)
        self.assertIn("Device2", device_names)
        self.assertIn("Device3", device_names)

        result = BatchUpgradeOperation.dry_run(build=build, group=group1)
        device_names = [d.name for d in result["devices"]]
        self.assertIn("Device1", device_names)
        self.assertNotIn("Device2", device_names)
        self.assertNotIn("Device3", device_names)

        result = BatchUpgradeOperation.dry_run(build=build, group=group2)
        device_names = [d.name for d in result["devices"]]
        self.assertNotIn("Device1", device_names)
        self.assertIn("Device2", device_names)
        self.assertNotIn("Device3", device_names)

    def test_build_find_related_device_firmwares_with_group(self):
        """Test _find_related_device_firmwares with group filtering."""
        org = self._get_org()
        category = self._create_category(organization=org)

        build1 = self._create_build(category=category, version="1.0")
        build2 = self._create_build(category=category, version="2.0")

        image1 = self._create_firmware_image(build=build1)

        group1 = self._create_device_group(name="Group 1", organization=org)
        group2 = self._create_device_group(name="Group 2", organization=org)

        device1 = self._create_device(
            name="Device1",
            organization=org,
            group=group1,
            model=image1.boards[0],
            mac_address="00:11:22:33:55:11",
        )
        device2 = self._create_device(
            name="Device2",
            organization=org,
            group=group2,
            model=image1.boards[0],
            mac_address="00:11:22:33:55:12",
        )
        device3 = self._create_device(
            name="Device3",
            organization=org,
            group=None,
            model=image1.boards[0],
            mac_address="00:11:22:33:55:13",
        )

        self._create_config(device=device1)
        self._create_config(device=device2)
        self._create_config(device=device3)

        unique_id = str(uuid.uuid4())[:8]
        credentials = self._create_credentials(
            name=f"test-creds-{unique_id}", organization=None, auto_add=True
        )

        for device in [device1, device2, device3]:
            if not DeviceConnection.objects.filter(
                device=device, credentials=credentials
            ).exists():
                self._create_device_connection(device=device, credentials=credentials)

        with mock.patch(
            "openwisp_firmware_upgrader.base.models.AbstractDeviceFirmware.create_upgrade_operation"
        ):
            DeviceFirmware.objects.create(device=device1, image=image1, installed=True)
            DeviceFirmware.objects.create(device=device2, image=image1, installed=True)
            DeviceFirmware.objects.create(device=device3, image=image1, installed=True)

        related = build2._find_related_device_firmwares(select_devices=True)
        device_names = [df.device.name for df in related]
        self.assertIn("Device1", device_names)
        self.assertIn("Device2", device_names)
        self.assertIn("Device3", device_names)

        related = build2._find_related_device_firmwares(
            select_devices=True, group=group1
        )
        device_names = [df.device.name for df in related]
        self.assertIn("Device1", device_names)
        self.assertNotIn("Device2", device_names)
        self.assertNotIn("Device3", device_names)

        related = build2._find_related_device_firmwares(
            select_devices=True, group=group2
        )
        device_names = [df.device.name for df in related]
        self.assertNotIn("Device1", device_names)
        self.assertIn("Device2", device_names)
        self.assertNotIn("Device3", device_names)

    def test_build_find_firmwareless_devices_with_group(self):
        """Test _find_firmwareless_devices with group filtering."""
        org = self._get_org()
        category = self._create_category(organization=org)
        build = self._create_build(category=category)
        image = self._create_firmware_image(build=build)

        group1 = self._create_device_group(name="Group 1", organization=org)
        group2 = self._create_device_group(name="Group 2", organization=org)

        device1 = self._create_device(
            name="Device1",
            organization=org,
            group=group1,
            model=image.boards[0],
            mac_address="00:11:22:33:55:21",
        )
        device2 = self._create_device(
            name="Device2",
            organization=org,
            group=group2,
            model=image.boards[0],
            mac_address="00:11:22:33:55:22",
        )
        device3 = self._create_device(
            name="Device3",
            organization=org,
            group=None,
            model=image.boards[0],
            mac_address="00:11:22:33:55:23",
        )

        self._create_config(device=device1)
        self._create_config(device=device2)
        self._create_config(device=device3)

        unique_id = str(uuid.uuid4())[:8]
        credentials = self._create_credentials(
            name=f"test-creds-{unique_id}", organization=None, auto_add=True
        )

        for device in [device1, device2, device3]:
            if not DeviceConnection.objects.filter(
                device=device, credentials=credentials
            ).exists():
                self._create_device_connection(device=device, credentials=credentials)

        devices = build._find_firmwareless_devices()
        device_names = [d.name for d in devices]
        self.assertIn("Device1", device_names)
        self.assertIn("Device2", device_names)
        self.assertIn("Device3", device_names)

        devices = build._find_firmwareless_devices(group=group1)
        device_names = [d.name for d in devices]
        self.assertIn("Device1", device_names)
        self.assertNotIn("Device2", device_names)
        self.assertNotIn("Device3", device_names)

        devices = build._find_firmwareless_devices(group=group2)
        device_names = [d.name for d in devices]
        self.assertNotIn("Device1", device_names)
        self.assertIn("Device2", device_names)
        self.assertNotIn("Device3", device_names)
