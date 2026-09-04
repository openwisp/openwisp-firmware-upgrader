import io
import threading
import time
import uuid
from contextlib import redirect_stdout
from unittest import mock
from unittest.mock import MagicMock, patch

import swapper
from celery.exceptions import Retry
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.db.models.query import QuerySet
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone

from openwisp_utils.tests import capture_any_output

from ..hardware import REVERSE_FIRMWARE_IMAGE_MAP
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
    image_type = "ar71xx-generic-xd3200-squashfs-sysupgrade.bin"

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

    def test_fw_str_appends_fw_version_when_it_differs_from_build_version(self):
        build = self._create_build(version="1.0")
        fw = self._create_firmware_image(build=build)

        with self.subTest("fw_version blank: not appended"):
            self.assertNotIn("(fw", str(fw))

        with self.subTest("fw_version matches build version: not appended"):
            FirmwareImage.objects.filter(pk=fw.pk).update(fw_version="1.0")
            fw.refresh_from_db()
            self.assertNotIn("(fw", str(fw))

        with self.subTest("fw_version differs from build version: appended"):
            FirmwareImage.objects.filter(pk=fw.pk).update(fw_version="23.05.5")
            fw.refresh_from_db()
            self.assertIn("(fw 23.05.5)", str(fw))

    def test_fw_str_new(self):
        fw = FirmwareImage()
        self.assertIsNotNone(str(fw))

    def test_fw_auto_type(self):
        fw = self._create_firmware_image(type="")
        self.assertEqual(fw.type, self.TPLINK_4300_IMAGE)

    def test_fw_auto_type_strips_version_from_filename(self):
        with open(self.FAKE_IMAGE_PATH, "rb") as f:
            content = f.read()
        file_v23 = SimpleUploadedFile(
            name=f"openwrt-23.05.5-{self.TPLINK_4300_IMAGE}",
            content=content,
            content_type="application/octet-stream",
        )
        file_v24 = SimpleUploadedFile(
            name=f"openwrt-24.10.0-{self.TPLINK_4300_IMAGE}",
            content=content,
            content_type="application/octet-stream",
        )
        fw23 = self._create_firmware_image(
            type="", file=file_v23, build=self._get_build(version="23.05.5")
        )
        fw24 = self._create_firmware_image(
            type="", file=file_v24, build=self._get_build(version="24.10.0")
        )
        self.assertEqual(fw23.type, fw24.type)
        self.assertEqual(fw23.type, self.TPLINK_4300_IMAGE)

    def test_reverse_firmware_image_map_unifi_6_boards(self):
        cases = (
            (
                "Ubiquiti UniFi 6 Plus",
                "mediatek-filogic-ubnt_unifi-6-plus-squashfs-sysupgrade.bin",
            ),
            (
                "Ubiquiti UniFi 6 Lite",
                "ramips-mt7621-ubnt_unifi-6-lite-squashfs-sysupgrade.bin",
            ),
            (
                "Ubiquiti UniFi 6 LR v1",
                "mediatek-mt7622-ubnt_unifi-6-lr-v1-squashfs-sysupgrade.bin",
            ),
            (
                "Ubiquiti UniFi 6 LR v2",
                "mediatek-mt7622-ubnt_unifi-6-lr-v2-squashfs-sysupgrade.bin",
            ),
            (
                "Ubiquiti UniFi 6 LR v3",
                "mediatek-mt7622-ubnt_unifi-6-lr-v3-squashfs-sysupgrade.bin",
            ),
        )
        for board, expected_type in cases:
            with self.subTest(board=board):
                self.assertEqual(REVERSE_FIRMWARE_IMAGE_MAP[board], expected_type)

    def test_clean_type_strips_directory_from_persisted_path(self):
        fw = self._create_firmware_image()
        fw.type = ""
        fw._clean_type()
        self.assertEqual(fw.type, self.TPLINK_4300_IMAGE)
        self.assertNotIn(str(fw.build.pk), fw.type)

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

    def test_device_fw_save_after_credentials_removed(self):
        """Regression test for #250."""
        device_fw = self._create_device_firmware(installed=True)
        device_fw.device.deviceconnection_set.all().delete()
        device_fw.full_clean()
        uo_count = UpgradeOperation.objects.count()
        device_fw.save(upgrade=False)
        self.assertEqual(UpgradeOperation.objects.count(), uo_count)

    def test_device_fw_uninstalled_without_credentials_rejected(self):
        """Reject saves that would start an upgrade with no credentials."""
        device_fw = self._create_device_firmware(installed=False)
        device_fw.device.deviceconnection_set.all().delete()
        with self.assertRaises(ValidationError) as ctx:
            device_fw.full_clean()
        self.assertIn("related connection", str(ctx.exception))

    def test_device_firmware_missing_required_fields(self):
        with self.assertRaises(ValidationError) as cm:
            DeviceFirmware().full_clean()
        self.assertIn("device", cm.exception.message_dict)
        self.assertIn("image", cm.exception.message_dict)

    def test_device_firmware_image_invalid_model(self):
        device_fw = self._create_device_firmware()
        different_img = self._create_firmware_image(
            build=device_fw.image.build, type=self.TPLINK_4300_IL_IMAGE
        )
        try:
            device_fw.image = different_img
            device_fw.full_clean()
        except ValidationError as e:
            self.assertIn("Device model and image do not match", str(e))
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

    def test_upgrade_operation_credentials_removed(self):
        """Regression test for #250."""
        device_fw = self._create_device_firmware()
        device = device_fw.device
        uo = UpgradeOperation(
            device=device,
            image=device_fw.image,
            upgrade_options={"n": True},
        )
        device.deviceconnection_set.all().delete()
        with self.assertRaises(ValidationError) as ctx:
            uo.full_clean()
        self.assertIn("connection", str(ctx.exception).lower())

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

    def test_upgrade_operation_update_progress(self):
        self._create_device_firmware(upgrade=True)
        uo = UpgradeOperation.objects.first()

        with self.subTest("Valid progress update to 50"):
            uo.update_progress(50)
            self.assertEqual(uo.progress, 50)

        with self.subTest("Valid progress update to 0"):
            uo.update_progress(0)
            self.assertEqual(uo.progress, 0)

        with self.subTest("Valid progress update to 100"):
            uo.update_progress(100)
            self.assertEqual(uo.progress, 100)

        with self.subTest("Invalid progress: non-numeric string"):
            with self.assertRaises(ValidationError) as context:
                uo.update_progress("50")
            self.assertEqual(
                context.exception.message, "Progress must be numeric, got <class 'str'>"
            )

        with self.subTest("Invalid progress: negative value"):
            with self.assertRaises(ValidationError) as context:
                uo.update_progress(-1)
            self.assertEqual(
                context.exception.message, "Progress must be between 0-100, got -1"
            )

        with self.subTest("Invalid progress: value over 100"):
            with self.assertRaises(ValidationError) as context:
                uo.update_progress(101)
            self.assertEqual(
                context.exception.message, "Progress must be between 0-100, got 101"
            )

        with self.subTest("Float value gets converted to int"):
            uo.update_progress(75.7)
            self.assertEqual(uo.progress, 75)

    def test_upgrade_operation_aborts_when_device_deactivated_before_worker_runs(self):
        device_fw = self._create_device_firmware()
        operation = UpgradeOperation(device=device_fw.device, image=device_fw.image)
        operation.full_clean()
        operation.save()
        device_fw.device.deactivate()
        with mock.patch.object(DeviceConnection, "get_working_connection") as mocked:
            operation.upgrade()
        mocked.assert_not_called()
        operation.refresh_from_db()
        self.assertEqual(operation.status, "aborted")
        self.assertIn("deactivated", operation.log)

    def test_concurrent_cancellation_race_condition(self):
        """Test that concurrent cancellation attempts don't cause errors."""
        self._create_device_firmware(upgrade=True)
        uo = UpgradeOperation.objects.first()
        with mock.patch.object(uo, "save"):
            # First call succeeds
            uo.cancel()
            # Second call should raise ValueError (already cancelled)
            with self.assertRaises(ValueError):
                uo.cancel()

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

    def test_create_for_device_shared_image(self):
        category = self._create_category(organization=None)
        build = self._create_build(category=category, os="OpenWrt 21.03")
        image = self._create_firmware_image(
            build=build, extraction_status=FirmwareImage.STATUS_SUCCESS
        )
        device = self._create_device(
            organization=self._get_org(),
            os=build.os,
            model=image.board,
        )
        self._create_config(device=device)
        self._create_device_connection(device=device)
        device_fw = DeviceFirmware.create_for_device(device)
        self.assertIsNotNone(device_fw)
        self.assertEqual(device_fw.image, image)

    def test_create_for_device_matches_board_and_os(self):
        image = self._create_firmware_image(
            extraction_status=FirmwareImage.STATUS_SUCCESS
        )
        build = image.build
        build.os = "OpenWrt 21.03"
        build.save()
        device = self._create_device(
            organization=build.category.organization,
            os=build.os,
            model=image.board,
        )
        self._create_config(device=device)
        self._create_device_connection(device=device)
        device_fw = DeviceFirmware.create_for_device(device)
        self.assertIsNotNone(device_fw)
        self.assertEqual(device_fw.image, image)

    def test_create_for_device_board_mismatch_returns_none(self):
        image = self._create_firmware_image(
            extraction_status=FirmwareImage.STATUS_SUCCESS
        )
        build = image.build
        build.os = "OpenWrt 21.03"
        build.save()
        device = self._create_device(
            organization=build.category.organization,
            os=build.os,
            model="some-other-board",
        )
        self._create_config(device=device)
        self.assertIsNone(DeviceFirmware.create_for_device(device))

    def test_create_for_device_os_mismatch_returns_none(self):
        image = self._create_firmware_image(
            extraction_status=FirmwareImage.STATUS_SUCCESS
        )
        build = image.build
        build.os = "OpenWrt 21.03"
        build.save()
        device = self._create_device(
            organization=build.category.organization,
            os="OpenWrt 19.07",
            model=image.board,
        )
        self._create_config(device=device)
        self.assertIsNone(DeviceFirmware.create_for_device(device))

    def test_create_for_device_skips_incompatible_compat_version(self):
        image = self._create_firmware_image(
            extraction_status=FirmwareImage.STATUS_SUCCESS,
        )
        image.compat_version = "1.1"
        image.save()
        build = image.build
        build.os = "OpenWrt 21.03"
        build.save()
        device = self._create_device(
            organization=build.category.organization,
            os=build.os,
            model=image.board,
        )
        self._create_config(device=device)
        self.assertIsNone(DeviceFirmware.create_for_device(device))

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

    def test_fw_auto_type_no_distro_prefix(self):
        with open(self.FAKE_IMAGE_PATH, "rb") as f:
            content = f.read()
        file = SimpleUploadedFile(
            name="ath79-generic-tplink_archer-c7-v4-squashfs-sysupgrade.bin",
            content=content,
            content_type="application/octet-stream",
        )
        fw = self._create_firmware_image(type="", file=file)
        self.assertEqual(
            fw.type, "ath79-generic-tplink_archer-c7-v4-squashfs-sysupgrade.bin"
        )

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

    def test_batch_upgrade_operation_str(self):
        build = self._create_build()
        batch = BatchUpgradeOperation.objects.create(build=build)
        expected = f"{build} ({timezone.localtime(batch.created).strftime('%Y-%m-%d %H:%M:%S')})"
        self.assertEqual(str(batch), expected)

    def test_upgrade_operation_str(self):
        with mock.patch(
            f"{self.app_label}.models.UpgradeOperation.upgrade", return_value=None
        ):
            self._create_device_firmware(upgrade=True)
        uo = UpgradeOperation.objects.first()
        expected = f"{uo.device} ({timezone.localtime(uo.created).strftime('%Y-%m-%d %H:%M:%S')})"
        self.assertEqual(str(uo), expected)

    def test_firmware_image_rejects_invalid_file_headers(self):
        build = self._get_build()
        invalid_headers = [
            (b"\xff\xd8\xff" + b"\x00" * 20, "JPEG"),
            (b"%PDF" + b"\x00" * 20, "PDF"),
            (b"\x89PNG\r\n\x1a\n" + b"\x00" * 20, "PNG"),
            (b"PK\x03\x04" + b"\x00" * 20, "ZIP"),
            (b"\x7fELF" + b"\x00" * 20, "ELF"),
        ]
        for content, label in invalid_headers:
            with self.subTest(file_type=label):
                fw = FirmwareImage(
                    build=build,
                    type=self.TPLINK_4300_IMAGE,
                    file=SimpleUploadedFile(
                        name=f"openwrt-{self.TPLINK_4300_IMAGE}",
                        content=content,
                        content_type="application/octet-stream",
                    ),
                )
                try:
                    fw.full_clean()
                except ValidationError as e:
                    self.assertIn("file", e.message_dict)
                else:
                    self.fail(f"ValidationError not raised for {label} file")

    def test_firmware_image_rejects_rootfs_image(self):
        build = self._get_build()
        fw = FirmwareImage(
            build=build,
            type=self.TPLINK_4300_IMAGE,
            file=SimpleUploadedFile(
                name="ath79-generic-tplink_tl-wdr4300-v1-squashfs-rootfs.img",
                content=b"\x00" * 100,
                content_type="application/octet-stream",
            ),
        )
        try:
            fw.full_clean()
        except ValidationError as e:
            self.assertIn("file", e.message_dict)
        else:
            self.fail("ValidationError not raised for rootfs image")

    def test_batch_upgrade_blocked_with_unconfirmed_images(self):
        env = self._create_upgrade_env()
        build = env["build2"]
        FirmwareImage.objects.filter(build=build).update(
            extraction_status=FirmwareImage.STATUS_UNCONFIRMED
        )
        with self.assertRaises(ValidationError) as ctx:
            build.batch_upgrade(firmwareless=False)
        self.assertIn("confirmed metadata", str(ctx.exception))

    def test_batch_upgrade_allowed_when_all_images_confirmed(self):
        env = self._create_upgrade_env()
        build = env["build2"]
        build.firmwareimage_set.update(extraction_status=FirmwareImage.STATUS_SUCCESS)
        batch = build.batch_upgrade(firmwareless=False)
        self.assertIsNotNone(batch)

    def test_update_extraction_status_single_image(self):
        cases = (
            (FirmwareImage.STATUS_SUCCESS, Build.BUILD_STATUS_SUCCESS),
            (FirmwareImage.STATUS_FAILED, Build.BUILD_STATUS_FAILED),
        )
        for image_status, expected in cases:
            with self.subTest(image_status=image_status):
                build = self._create_build(version=f"0.1-{image_status}")
                build.status = Build.BUILD_STATUS_ANALYZING
                build.save()
                image = self._create_firmware_image(build=build)
                image.extraction_status = image_status
                image.save()
                build.update_extraction_status()
                build.refresh_from_db()
                self.assertEqual(build.status, expected)

    def test_update_extraction_status_analyzing_takes_priority(self):
        build = self._create_build()
        build.status = Build.BUILD_STATUS_ANALYZING
        build.save()
        image1 = self._create_firmware_image(build=build)
        image1.extraction_status = FirmwareImage.STATUS_FAILED
        image1.save()
        image2 = self._create_firmware_image(
            build=build, type=self.TPLINK_4300_IL_IMAGE
        )
        image2.extraction_status = FirmwareImage.STATUS_IN_PROGRESS
        image2.save()
        build.update_extraction_status()
        build.refresh_from_db()
        self.assertEqual(build.status, Build.BUILD_STATUS_ANALYZING)

    def test_update_extraction_status_does_not_overwrite_final_with_analyzing(self):
        env = self._create_upgrade_env()
        build = env["build2"]
        Build.objects.filter(pk=build.pk).update(status=Build.BUILD_STATUS_SUCCESS)
        FirmwareImage.objects.filter(pk=env["image2a"].pk).update(
            extraction_status=FirmwareImage.STATUS_IN_PROGRESS
        )
        build.refresh_from_db()
        build.update_extraction_status()
        build.refresh_from_db()
        self.assertEqual(build.status, Build.BUILD_STATUS_SUCCESS)

    def test_validate_locked_blocks_field_change_on_success(self):
        image = self._create_firmware_image()
        image.extraction_status = FirmwareImage.STATUS_SUCCESS
        image.board = "TP-Link WDR4300"
        image.target = "ath79/generic"
        image.source = "fwtool"
        image.save()
        original = (
            FirmwareImage.objects.filter(pk=image.pk)
            .values(
                "extraction_status",
                "board",
                "compatible",
                "target",
                "fw_version",
                "compat_version",
                "source",
            )
            .first()
        )
        image.board = "Changed board"
        with self.assertRaises(ValidationError) as ctx:
            image._validate_locked(original)
        self.assertIn("read-only", str(ctx.exception))

    def test_validate_file_replacement_blocks_when_referenced_by_device_firmware(self):
        image = self._create_firmware_image()
        device = self._create_device(organization=image.build.category.organization)
        self._create_config(device=device)
        self._create_device_connection(device=device)
        DeviceFirmware.objects.create(device=device, image=image, installed=True)
        original = FirmwareImage.objects.filter(pk=image.pk).values("file").first()
        image.file = self._get_simpleuploadedfile(self.FAKE_IMAGE_PATH)
        with self.assertRaises(ValidationError) as ctx:
            image._validate_file_replacement(original)
        self.assertIn("file", ctx.exception.message_dict)

    def test_firmware_image_model_save_file_replacement_resets_and_reextracts(self):
        fw = self._create_firmware_image()
        FirmwareImage.objects.filter(pk=fw.pk).update(
            extraction_status=FirmwareImage.STATUS_SUCCESS,
            board="TP-Link WDR4300",
            compatible="tplink,tl-wdr4300-v1",
            target="ath79/generic",
            fw_version="23.05.5",
            compat_version="1.0",
            source="fwtool",
        )
        fw.refresh_from_db()
        storage = FirmwareImage.file.field.storage
        old_file_name = fw.file.name
        self.assertTrue(storage.exists(old_file_name))
        with mock.patch(
            "openwisp_firmware_upgrader.base.models.extract_firmware_metadata"
        ) as mock_task:
            with self.captureOnCommitCallbacks(execute=True):
                fw.file = self._get_simpleuploadedfile(self.FAKE_IMAGE_PATH2)
                fw.save()
        fw.refresh_from_db()
        self.assertEqual(fw.extraction_status, FirmwareImage.STATUS_UNCONFIRMED)
        self.assertEqual(fw.board, "")
        self.assertEqual(fw.compatible, "")
        self.assertEqual(fw.target, "")
        self.assertEqual(fw.fw_version, "")
        self.assertEqual(fw.compat_version, "")
        self.assertEqual(fw.source, "")
        self.assertFalse(storage.exists(old_file_name))
        mock_task.delay.assert_called_once_with(str(fw.pk))

    def test_firmware_image_save_update_fields_preserves_metadata_reset(self):
        fw = self._create_firmware_image()
        FirmwareImage.objects.filter(pk=fw.pk).update(
            extraction_status=FirmwareImage.STATUS_SUCCESS,
            board="TP-Link WDR4300",
            compatible="tplink,tl-wdr4300-v1",
            target="ath79/generic",
            fw_version="23.05.5",
            compat_version="1.0",
            source="fwtool",
        )
        fw.refresh_from_db()
        fw.file = self._get_simpleuploadedfile(self.FAKE_IMAGE_PATH2)
        fw.save(update_fields=["file"])
        fw.refresh_from_db()
        self.assertEqual(fw.extraction_status, FirmwareImage.STATUS_UNCONFIRMED)
        self.assertEqual(fw.board, "")
        self.assertEqual(fw.compatible, "")
        self.assertEqual(fw.target, "")
        self.assertEqual(fw.fw_version, "")
        self.assertEqual(fw.compat_version, "")
        self.assertEqual(fw.source, "")

    def test_validate_build_unchanged_blocks_persisted_change(self):
        image = self._create_firmware_image()
        other_build = self._create_build(category=image.build.category, version="99.0")
        original = FirmwareImage.objects.filter(pk=image.pk).values("build_id").first()
        image.build = other_build
        with self.assertRaises(ValidationError) as ctx:
            image._validate_build_unchanged(original)
        self.assertIn("build", ctx.exception.message_dict)

    def test_validate_locked_allows_change_when_failed(self):
        image = self._create_firmware_image()
        image.extraction_status = FirmwareImage.STATUS_FAILED
        image.board = ""
        image.save()
        original = (
            FirmwareImage.objects.filter(pk=image.pk)
            .values(
                "extraction_status",
                "board",
                "compatible",
                "target",
                "fw_version",
                "compat_version",
                "source",
            )
            .first()
        )
        image.board = "Manually entered"
        image._validate_locked(original)

    def test_validate_locked_allows_filling_empty_locked_fields(self):
        image = self._create_firmware_image()
        image.extraction_status = FirmwareImage.STATUS_MANUALLY_CONFIRMED
        image.board = "Orange Pi Zero"
        image.target = ""
        image.source = "manual"
        image.save()
        original = (
            FirmwareImage.objects.filter(pk=image.pk)
            .values(
                "extraction_status",
                "board",
                "compatible",
                "target",
                "fw_version",
                "compat_version",
                "source",
            )
            .first()
        )
        image.target = "sunxi/cortexa7"
        image._validate_locked(original)

    def test_validate_locked_blocks_bypass_via_status_change(self):
        image = self._create_firmware_image()
        image.extraction_status = FirmwareImage.STATUS_SUCCESS
        image.board = "TP-Link WDR4300"
        image.target = "ath79/generic"
        image.source = "fwtool"
        image.save()
        original = (
            FirmwareImage.objects.filter(pk=image.pk)
            .values(
                "extraction_status",
                "board",
                "compatible",
                "target",
                "fw_version",
                "compat_version",
                "source",
            )
            .first()
        )
        image.extraction_status = FirmwareImage.STATUS_FAILED
        image.board = "Tampered board"
        with self.assertRaises(ValidationError) as ctx:
            image._validate_locked(original)
        self.assertIn("read-only", str(ctx.exception))

    @capture_any_output()
    def test_device_firmware_clean_blocks_unconfirmed_image(self):
        image = self._create_firmware_image()
        FirmwareImage.objects.filter(pk=image.pk).update(
            extraction_status=FirmwareImage.STATUS_UNCONFIRMED
        )
        image.refresh_from_db()
        device = self._create_device(organization=image.build.category.organization)
        self._create_config(device=device)
        device_fw = DeviceFirmware()
        device_fw.image = image
        device_fw.device = device
        with self.assertRaises(ValidationError) as ctx:
            device_fw.clean()
        self.assertIn("image", ctx.exception.message_dict)

    def test_device_firmware_clean_blocks_locked_image_without_board(self):
        image = self._create_firmware_image()
        FirmwareImage.objects.filter(pk=image.pk).update(
            extraction_status=FirmwareImage.STATUS_MANUALLY_CONFIRMED,
            board="",
        )
        image.refresh_from_db()
        device = self._create_device(organization=image.build.category.organization)
        self._create_config(device=device)
        self._create_device_connection(device=device)
        device_fw = DeviceFirmware()
        device_fw.image = image
        device_fw.device = device
        with self.assertRaises(ValidationError) as ctx:
            device_fw.clean()
        self.assertIn("This firmware image has no board value.", str(ctx.exception))

    def test_auto_create_device_firmwares_skip_unconfirmed(self):
        image = self._create_firmware_image()
        image.extraction_status = FirmwareImage.STATUS_UNCONFIRMED
        image.save()
        with mock.patch("django.db.transaction.on_commit") as mock_on_commit:
            DeviceFirmware.auto_create_device_firmwares(instance=image, created=False)
            mock_on_commit.assert_not_called()

    def test_auto_create_device_firmwares_triggers_on_pairing_eligible_status(self):
        for i, eligible_status in enumerate(
            (
                FirmwareImage.STATUS_SUCCESS,
                FirmwareImage.STATUS_INCOMPLETE,
                FirmwareImage.STATUS_MANUALLY_CONFIRMED,
            )
        ):
            with self.subTest(extraction_status=eligible_status):
                image = self._create_firmware_image(
                    extraction_status=FirmwareImage.STATUS_UNCONFIRMED,
                    type=f"pairing-eligible-{i}",
                )
                image.extraction_status = eligible_status
                with mock.patch("django.db.transaction.on_commit") as mock_on_commit:
                    DeviceFirmware.auto_create_device_firmwares(
                        instance=image, created=False
                    )
                    mock_on_commit.assert_called_once()

    def test_auto_create_device_firmwares_skips_already_confirmed_resave(self):
        image = self._create_firmware_image()
        FirmwareImage.objects.filter(pk=image.pk).update(
            extraction_status=FirmwareImage.STATUS_SUCCESS
        )
        image = FirmwareImage.objects.get(pk=image.pk)
        with mock.patch("django.db.transaction.on_commit") as mock_on_commit:
            DeviceFirmware.auto_create_device_firmwares(instance=image, created=False)
            mock_on_commit.assert_not_called()


class TestModelsTransaction(TestUpgraderMixin, TransactionTestCase):
    _mock_updrade = "openwisp_firmware_upgrader.upgraders.openwrt.OpenWrt.upgrade"
    _mock_connect = "openwisp_controller.connection.models.DeviceConnection.connect"
    os = TestModels.os
    image_type = TestModels.image_type

    @mock.patch(_mock_updrade, return_value=True)
    def test_dry_run(self, *args):
        with mock.patch(self._mock_connect, return_value=True):
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
    def test_upgrade_related_devices(self, *args):
        with mock.patch(self._mock_connect, return_value=True):
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
    def test_upgrade_firmwareless_devices(self, *args):
        with mock.patch(self._mock_connect, return_value=True):
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
    def test_upgrade_related_devices_existing_fw(self, *args):
        with mock.patch(self._mock_connect, return_value=True):
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

    @mock.patch(_mock_updrade, return_value=True)
    def test_batch_upgrade_with_group_filtering(self, *_args):
        """Test complete batch upgrade workflow with group filtering."""
        with mock.patch(self._mock_connect, return_value=True):
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
                    self._create_device_connection(
                        device=device, credentials=credentials
                    )
            with mock.patch(
                "openwisp_firmware_upgrader.base.models.AbstractDeviceFirmware.create_upgrade_operation"
            ):
                DeviceFirmware.objects.create(
                    device=device1, image=image1, installed=True
                )
                DeviceFirmware.objects.create(
                    device=device2, image=image1, installed=True
                )
                DeviceFirmware.objects.create(
                    device=device3, image=image1, installed=True
                )
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
    def test_batch_upgrade_with_location_filtering(self, *_args):
        """Test complete batch upgrade workflow with location filtering."""
        with mock.patch(self._mock_connect, return_value=True):
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
                    self._create_device_connection(
                        device=device, credentials=credentials
                    )

            # Create device firmware objects
            with mock.patch(
                "openwisp_firmware_upgrader.base.models.AbstractDeviceFirmware.create_upgrade_operation"
            ):
                DeviceFirmware.objects.create(
                    device=device1, image=image1, installed=True
                )
                DeviceFirmware.objects.create(
                    device=device2, image=image1, installed=True
                )
                DeviceFirmware.objects.create(
                    device=device3, image=image1, installed=True
                )

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
    def test_batch_upgrade_with_group_and_location_filtering(self, *_args):
        """Test batch upgrade with both group and location filtering."""
        with mock.patch(self._mock_connect, return_value=True):
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
            unique_id = str(uuid.uuid4())[:8]
            credentials = self._create_credentials(
                name=f"test-creds-{unique_id}", organization=None, auto_add=True
            )
            for device in [device1, device2, device3]:
                self._create_config(device=device)
                if not DeviceConnection.objects.filter(
                    device=device, credentials=credentials
                ).exists():
                    self._create_device_connection(
                        device=device, credentials=credentials
                    )
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

    @mock.patch(
        "openwisp_controller.connection.apps.ConnectionConfig._launch_update_config"
    )
    @mock.patch("openwisp_firmware_upgrader.websockets._run_coroutine_safely")
    @mock.patch("openwisp_firmware_upgrader.tasks.upgrade_firmware.delay")
    def test_batch_upgrade_excludes_deactivated_devices(self, *args):
        env = self._create_upgrade_env()
        # Test firmwareless=False case (devices with existing DeviceFirmware)
        env["d1"].deactivate()
        batch = env["build2"].batch_upgrade(firmwareless=False)
        ops = UpgradeOperation.objects.filter(batch=batch)
        # Should only have operations for non-deactivated devices
        device_ids = [op.device.pk for op in ops]
        self.assertNotIn(env["d1"].pk, device_ids)  # deactivated device excluded
        self.assertIn(env["d2"].pk, device_ids)  # active device included

        # Clean up for next test
        UpgradeOperation.objects.all().delete()
        BatchUpgradeOperation.objects.all().delete()

        # Test firmwareless=True case (devices without existing DeviceFirmware)
        # Create a new device without DeviceFirmware and deactivate it
        firmwareless_device = self._create_device(
            name="FirmwarelessDevice",
            organization=env["d1"].organization,
            model=env["image2a"].boards[0],
            mac_address="00:11:22:33:44:55",
        )
        self._create_config(device=firmwareless_device)
        self._create_device_connection(
            device=firmwareless_device,
            credentials=env["d1"].deviceconnection_set.first().credentials,
        )
        firmwareless_device.deactivate()

        active_firmwareless_device = self._create_device(
            name="ActiveFirmwarelessDevice",
            organization=env["d1"].organization,
            model=env["image2a"].boards[0],
            mac_address="00:11:22:33:44:56",
        )
        self._create_config(device=active_firmwareless_device)
        self._create_device_connection(
            device=active_firmwareless_device,
            credentials=env["d1"].deviceconnection_set.first().credentials,
        )

        batch = env["build2"].batch_upgrade(firmwareless=True)
        ops = UpgradeOperation.objects.filter(batch=batch)
        # Deactivated firmwareless device should be excluded
        device_ids = [op.device.pk for op in ops]
        self.assertNotIn(
            firmwareless_device.pk, device_ids
        )  # deactivated firmwareless device excluded
        self.assertIn(
            active_firmwareless_device.pk, device_ids
        )  # active firmwareless device included

    @mock.patch(
        "openwisp_controller.connection.apps.ConnectionConfig._launch_update_config"
    )
    def test_deactivated_device_validation(self, *_args):
        device_fw = self._create_device_firmware()
        device = device_fw.device
        # Test DeviceFirmware validation
        device.deactivate()
        with self.assertRaises(ValidationError) as cm:
            new_device_fw = DeviceFirmware(device=device, image=device_fw.image)
            new_device_fw.full_clean()
        self.assertIn(
            "Firmware upgrades are not allowed for deactivated devices.",
            str(cm.exception),
        )
        # Test UpgradeOperation validation
        with self.assertRaises(ValidationError) as cm:
            operation = UpgradeOperation(device=device, image=device_fw.image)
            operation.full_clean()
        self.assertIn(
            "Upgrade operations are not allowed for deactivated devices.",
            str(cm.exception),
        )

    @skipUnlessDBFeature("has_select_for_update")
    def test_update_extraction_status_locks_against_concurrent_file_replacement(self):
        build = self._create_build()
        image1 = self._create_firmware_image(build=build, type=self.TPLINK_4300_IMAGE)
        image2 = self._create_firmware_image(
            build=build, type=self.TPLINK_4300_IL_IMAGE
        )
        FirmwareImage.objects.filter(pk__in=[image1.pk, image2.pk]).update(
            extraction_status=FirmwareImage.STATUS_SUCCESS
        )
        Build.objects.filter(pk=build.pk).update(status=Build.BUILD_STATUS_ANALYZING)

        images_read = threading.Event()
        concurrent_write_done = threading.Event()
        errors = []

        def replace_file_concurrently():
            try:
                images_read.wait(timeout=5)
                FirmwareImage.objects.filter(pk=image1.pk).update(
                    extraction_status=FirmwareImage.STATUS_UNCONFIRMED
                )
                Build.objects.filter(pk=build.pk).update(
                    status=Build.BUILD_STATUS_ANALYZING
                )
            except Exception as error:
                errors.append(error)
            finally:
                concurrent_write_done.set()
                connection.close()

        original_fetch_all = QuerySet._fetch_all

        def racy_fetch_all(self):
            original_fetch_all(self)
            if self.model is FirmwareImage and not images_read.is_set():
                images_read.set()
                time.sleep(0.3)

        thread = threading.Thread(target=replace_file_concurrently)
        thread.start()
        with mock.patch.object(QuerySet, "_fetch_all", racy_fetch_all):
            build.update_extraction_status()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive(), "concurrent thread did not finish in time")
        self.assertTrue(
            concurrent_write_done.is_set(),
            "concurrent thread never completed its write",
        )
        self.assertEqual(errors, [])
        build.refresh_from_db()
        self.assertEqual(build.status, Build.BUILD_STATUS_ANALYZING)


class TestFirmwareImageValidation(TestUpgraderMixin, TestCase):
    def _make_firmware_image(self, content, filename=None):
        if filename is None:
            filename = f"openwrt-{self.TPLINK_4300_IMAGE}"
        return FirmwareImage(
            build=self._get_build(),
            file=SimpleUploadedFile(
                filename, content, content_type="application/octet-stream"
            ),
            type=self.TPLINK_4300_IMAGE,
        )

    def test_validate_file_header(self):
        with self.subTest("jpeg header raises ValidationError"):
            fw = self._make_firmware_image(b"\xff\xd8\xff\xe0" + b"\x00" * 12)
            try:
                fw._validate_file_header(None)
            except ValidationError as e:
                self.assertIn("file", e.message_dict)
                self.assertIn("JPEG", str(e))
            else:
                self.fail("ValidationError not raised for JPEG header")

        with self.subTest("pdf header raises ValidationError"):
            fw = self._make_firmware_image(b"%PDF-1.4" + b"\x00" * 8)
            try:
                fw._validate_file_header(None)
            except ValidationError as e:
                self.assertIn("file", e.message_dict)
                self.assertIn("PDF", str(e))
            else:
                self.fail("ValidationError not raised for PDF header")

        with self.subTest("png header raises ValidationError"):
            fw = self._make_firmware_image(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
            try:
                fw._validate_file_header(None)
            except ValidationError as e:
                self.assertIn("file", e.message_dict)
                self.assertIn("PNG", str(e))
            else:
                self.fail("ValidationError not raised for PNG header")

        with self.subTest("gif87a header raises ValidationError"):
            fw = self._make_firmware_image(b"GIF87a" + b"\x00" * 10)
            try:
                fw._validate_file_header(None)
            except ValidationError as e:
                self.assertIn("file", e.message_dict)
                self.assertIn("GIF", str(e))
            else:
                self.fail("ValidationError not raised for GIF87a header")

        with self.subTest("gif89a header raises ValidationError"):
            fw = self._make_firmware_image(b"GIF89a" + b"\x00" * 10)
            try:
                fw._validate_file_header(None)
            except ValidationError as e:
                self.assertIn("file", e.message_dict)
                self.assertIn("GIF", str(e))
            else:
                self.fail("ValidationError not raised for GIF89a header")

        with self.subTest("zip header raises ValidationError"):
            fw = self._make_firmware_image(b"PK\x03\x04" + b"\x00" * 12)
            try:
                fw._validate_file_header(None)
            except ValidationError as e:
                self.assertIn("file", e.message_dict)
                self.assertIn("ZIP", str(e))
            else:
                self.fail("ValidationError not raised for ZIP header")

        with self.subTest("elf header raises ValidationError"):
            fw = self._make_firmware_image(b"\x7fELF" + b"\x00" * 12)
            try:
                fw._validate_file_header(None)
            except ValidationError as e:
                self.assertIn("file", e.message_dict)
                self.assertIn("ELF", str(e))
            else:
                self.fail("ValidationError not raised for ELF header")

        with self.subTest("html header raises ValidationError"):
            fw = self._make_firmware_image(b"<html" + b"\x00" * 11)
            try:
                fw._validate_file_header(None)
            except ValidationError as e:
                self.assertIn("file", e.message_dict)
                self.assertIn("HTML", str(e))
            else:
                self.fail("ValidationError not raised for HTML header")

        with self.subTest("html doctype header raises ValidationError"):
            fw = self._make_firmware_image(b"<!DOC" + b"\x00" * 11)
            try:
                fw._validate_file_header(None)
            except ValidationError as e:
                self.assertIn("file", e.message_dict)
                self.assertIn("HTML", str(e))
            else:
                self.fail("ValidationError not raised for HTML doctype header")

        with self.subTest("xml header raises ValidationError"):
            fw = self._make_firmware_image(b"<?xml" + b"\x00" * 11)
            try:
                fw._validate_file_header(None)
            except ValidationError as e:
                self.assertIn("file", e.message_dict)
                self.assertIn("XML", str(e))
            else:
                self.fail("ValidationError not raised for XML header")

        with self.subTest("valid squashfs header passes"):
            fw = self._make_firmware_image(b"sqsh" + b"\x00" * 12)
            fw._validate_file_header(None)  # must not raise

        with self.subTest("no file set is handled gracefully"):
            fw = FirmwareImage()
            fw.file = None
            fw._validate_file_header(None)  # must not raise

        with self.subTest("ioerror on file seek is handled gracefully"):
            fw = FirmwareImage()
            mock_file = mock.MagicMock()
            mock_file.seek.side_effect = IOError("storage error")
            fw.file = mock_file
            fw._validate_file_header(None)  # must not raise

    def test_validate_rootfs(self):
        with self.subTest("rootfs filename raises ValidationError"):
            fw = self._make_firmware_image(
                b"\x00" * 16,
                filename="openwrt-ath79-generic-device-rootfs.img",
            )
            try:
                fw._validate_rootfs()
            except ValidationError as e:
                self.assertIn("file", e.message_dict)
                self.assertIn("rootfs", str(e))
            else:
                self.fail("ValidationError not raised for rootfs filename")

        with self.subTest("sysupgrade filename passes"):
            fw = self._make_firmware_image(
                b"\x00" * 16,
                filename=f"openwrt-{self.TPLINK_4300_IMAGE}",
            )
            fw._validate_rootfs()  # must not raise

        with self.subTest("rootfs as a non-final token passes"):
            fw = self._make_firmware_image(
                b"\x00" * 10,
                filename="openwrt-ath79-generic-device-rootfs-squashfs-sysupgrade.bin",
            )
            fw._validate_rootfs()  # must not raise

        with self.subTest("uppercase rootfs filename raises ValidationError"):
            fw = self._make_firmware_image(
                b"\x00" * 16,
                filename="openwrt-ath79-generic-device-rootfs.IMG",
            )
            try:
                fw._validate_rootfs()
            except ValidationError as e:
                self.assertIn("file", e.message_dict)
                self.assertIn("rootfs", str(e))
            else:
                self.fail("ValidationError not raised for uppercase rootfs filename")

        with self.subTest("rootfs .bin filename raises ValidationError"):
            fw = self._make_firmware_image(
                b"\x00" * 16,
                filename="openwrt-ath79-generic-device-rootfs.bin",
            )
            try:
                fw._validate_rootfs()
            except ValidationError as e:
                self.assertIn("file", e.message_dict)
                self.assertIn("rootfs", str(e))
            else:
                self.fail("ValidationError not raised for rootfs .bin filename")

        with self.subTest("compressed rootfs tarball raises ValidationError"):
            fw = self._make_firmware_image(
                b"\x00" * 16,
                filename="openwrt-ath79-generic-device-rootfs.tar.gz",
            )
            try:
                fw._validate_rootfs()
            except ValidationError as e:
                self.assertIn("file", e.message_dict)
                self.assertIn("rootfs", str(e))
            else:
                self.fail("ValidationError not raised for rootfs .tar.gz filename")

        with self.subTest("clean() calls _validate_rootfs"):
            fw = self._make_firmware_image(
                b"\x00" * 16,
                filename="openwrt-ath79-generic-device-rootfs.img",
            )
            try:
                fw.full_clean()
            except ValidationError as e:
                self.assertIn("file", e.message_dict)
                self.assertIn("rootfs", str(e))
            else:
                self.fail("ValidationError not raised through full_clean()")
