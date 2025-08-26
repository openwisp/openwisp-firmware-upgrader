import io
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

    def test_device_fw_not_created_on_device_connection_save(self):
        org = self._get_org()
        category = self._get_category(organization=org)
        build1 = self._create_build(category=category, version="0.1", os=self.os)
        image1a = self._create_firmware_image(build=build1, type=self.image_type)

        with self.subTest("Device doesn't define os"):
            d1 = self._create_device_with_connection(os="", model=image1a.boards[0])
            self.assertEqual(DeviceConnection.objects.count(), 1)
            self.assertEqual(Device.objects.count(), 1)
            self.assertEqual(DeviceFirmware.objects.count(), 0)
            d1.delete(check_deactivated=False)
            Credentials.objects.all().delete()

        with self.subTest("Device doesn't define model"):
            d1 = self._create_device_with_connection(os=self.os, model="")
            self.assertEqual(DeviceConnection.objects.count(), 1)
            self.assertEqual(Device.objects.count(), 1)
            self.assertEqual(DeviceFirmware.objects.count(), 0)
            d1.delete(check_deactivated=False)
            Credentials.objects.all().delete()

        build1.os = None
        build1.save()

        with self.subTest("Build doesn't define os"):
            d1 = self._create_device_with_connection(
                model=image1a.boards[0], os=self.os
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
        self._create_device_with_connection(os=self.os, model=image1a.boards[0])
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

    def test_delete_firmware_files_on_build_delete(self):
        """Test that firmware files are deleted when a build is deleted"""
        file_storage_backend = FirmwareImage.file.field.storage
        build = self._create_build()
        image = self._create_firmware_image(build=build)
        file_name = image.file.name
        # Delete the build
        build.delete()
        # Check that the file was deleted
        self.assertEqual(file_storage_backend.exists(file_name), False)

    def test_delete_firmware_files_on_category_delete(self):
        """Test that firmware files are deleted when a category is deleted"""
        file_storage_backend = FirmwareImage.file.field.storage
        category = self._create_category()
        build = self._create_build(category=category)
        image = self._create_firmware_image(build=build)
        file_name = image.file.name
        # Delete the category
        category.delete()
        # Check that the file was deleted
        self.assertEqual(file_storage_backend.exists(file_name), False)

    def test_delete_firmware_files_on_organization_delete(self):
        """Test that firmware files are deleted when an organization is deleted"""
        file_storage_backend = FirmwareImage.file.field.storage
        org = self._get_org()
        category = self._create_category(organization=org)
        build = self._create_build(category=category)
        image = self._create_firmware_image(build=build)
        file_name = image.file.name
        # Delete the organization
        org.delete()
        # Check that the file was deleted
        self.assertEqual(file_storage_backend.exists(file_name), False)
