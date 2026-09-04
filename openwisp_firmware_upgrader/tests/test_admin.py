import json
import re
from datetime import timedelta
from unittest import mock

import django
import swapper
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils.timezone import localtime

from openwisp_controller.config.tests.test_admin import TestAdmin as TestConfigAdmin
from openwisp_controller.connection import settings as conn_settings
from openwisp_firmware_upgrader.admin import (
    BatchUpgradeConfirmationForm,
    BuildAdmin,
    DeviceAdmin,
    DeviceFirmwareForm,
    DeviceFirmwareInline,
    DeviceUpgradeOperationInline,
    FirmwareImageAdmin,
    FirmwareImageInline,
    admin,
)
from openwisp_users.tests.utils import TestMultitenantAdminMixin
from openwisp_utils.tests import AdminActionPermTestMixin, capture_stderr

from .. import settings as app_settings
from .. import tasks
from ..swapper import load_model
from ..upgraders.openwisp import OpenWisp1
from .base import TestUpgraderMixin

User = get_user_model()

Build = load_model("Build")
Category = load_model("Category")
DeviceFirmware = load_model("DeviceFirmware")
FirmwareImage = load_model("FirmwareImage")
UpgradeOperation = load_model("UpgradeOperation")
BatchUpgradeOperation = load_model("BatchUpgradeOperation")
Device = swapper.load_model("config", "Device")
Organization = swapper.load_model("openwisp_users", "Organization")
Location = swapper.load_model("geo", "Location")
DeviceLocation = swapper.load_model("geo", "DeviceLocation")
DeviceConnection = swapper.load_model("connection", "DeviceConnection")


class MockRequest:
    pass


class BaseTestAdmin(TestMultitenantAdminMixin, TestUpgraderMixin):
    app_label = Build._meta.app_label
    config_app_label = Device._meta.app_label
    _device_params = TestConfigAdmin._device_params.copy()
    _device_params.update(
        {
            "devicefirmware-0-image": "",
            "devicefirmware-0-id": "",
            "devicefirmware-TOTAL_FORMS": 0,
            "devicefirmware-INITIAL_FORMS": 0,
            "devicefirmware-MIN_NUM_FORMS": 0,
            "devicefirmware-MAX_NUM_FORMS": 1,
            "deviceconnection_set-TOTAL_FORMS": 1,
            "deviceconnection_set-INITIAL_FORMS": 1,
            "devicelocation-TOTAL_FORMS": 1,
            "devicelocation-INITIAL_FORMS": 0,
            "devicelocation-MIN_NUM_FORMS": 0,
            "devicelocation-MAX_NUM_FORMS": 1,
            "config-INITIAL_FORMS": 1,
        }
    )

    def _get_device_params(
        self, device, device_conn, fw_image, device_fw=None, upgrade_options=""
    ):
        device_params = self._device_params.copy()
        device_params.update(
            {
                "model": device.model,
                "organization": str(device.organization.id),
                "config-0-id": str(device.config.pk),
                "config-0-device": str(device.id),
                "deviceconnection_set-0-credentials": str(device_conn.credentials_id),
                "deviceconnection_set-0-id": str(device_conn.id),
                "deviceconnection_set-0-update_strategy": device_conn.update_strategy,
                "devicefirmware-0-image": str(fw_image.id),
                "devicefirmware-0-upgrade_options": upgrade_options,
                "deviceconnection_set-0-enabled": True,
                "devicefirmware-TOTAL_FORMS": 1,
                "devicefirmware-INITIAL_FORMS": 0,
                "upgradeoperation_set-TOTAL_FORMS": 0,
                "upgradeoperation_set-INITIAL_FORMS": 0,
                "upgradeoperation_set-MIN_NUM_FORMS": 0,
                "upgradeoperation_set-MAX_NUM_FORMS": 0,
                "_continue": True,
            }
        )
        if device_fw:
            device_params.update(
                {
                    "devicefirmware-0-id": str(device_fw.id),
                    "devicefirmware-TOTAL_FORMS": 1,
                    "devicefirmware-INITIAL_FORMS": 1,
                }
            )
        return device_params

    def setUp(self, *args, **kwargs):
        super().setUp(*args, **kwargs)
        self.factory = RequestFactory()

    def make_device_admin_request(self, pk):
        return self.factory.get(
            reverse(f"admin:{self.config_app_label}_device_change", args=[pk])
        )

    @property
    def build_list_url(self):
        return reverse(f"admin:{self.app_label}_build_changelist")


@override_settings(LANGUAGE_CODE="en")
class TestAdmin(BaseTestAdmin, TestCase):
    _mock_upgrade = "openwisp_firmware_upgrader.upgraders.openwrt.OpenWrt.upgrade"
    _mock_connect = "openwisp_controller.connection.models.DeviceConnection.connect"

    def test_build_list(self):
        self._login()
        build = self._create_build()
        r = self.client.get(self.build_list_url)
        self.assertContains(r, str(build))

    def test_build_list_upgrade_action(self):
        self._login()
        self._create_build()
        r = self.client.get(self.build_list_url)
        self.assertContains(r, '<option value="upgrade_selected">')

    def test_upgrade_build_admin(self):
        self._login()
        b = self._create_build()
        path = reverse(f"admin:{self.app_label}_build_change", args=[b.pk])
        r = self.client.get(path)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Launch mass upgrade operation")

    def test_upgrade_selected_error(self):
        self._login()
        b1 = self._create_build()
        b2 = self._create_build(version="0.2", category=b1.category)
        r = self.client.post(
            self.build_list_url,
            {"action": "upgrade_selected", ACTION_CHECKBOX_NAME: (b1.pk, b2.pk)},
            follow=True,
        )
        self.assertContains(r, '<li class="error">')
        self.assertContains(
            r, "only a single mass upgrade operation at time is supported"
        )

    def test_upgrade_intermediate_page_related(self):
        self._login()
        env = self._create_upgrade_env()
        with self.assertNumQueries(15):
            r = self.client.post(
                self.build_list_url,
                {
                    "action": "upgrade_selected",
                    ACTION_CHECKBOX_NAME: (env["build2"].pk,),
                },
                follow=True,
            )
        self.assertNotContains(r, '<input type="submit" name="upgrade_related"')

    def test_upgrade_intermediate_page_firmwareless(self):
        self._login()
        env = self._create_upgrade_env(device_firmware=False)
        with self.assertNumQueries(14):
            r = self.client.post(
                self.build_list_url,
                {
                    "action": "upgrade_selected",
                    ACTION_CHECKBOX_NAME: (env["build2"].pk,),
                },
                follow=True,
            )
        self.assertNotContains(
            r,
            'name="upgrade_related"',
        )
        self.assertContains(r, 'name="upgrade_all"')

    def test_view_device_administrator(self):
        device_fw = self._create_device_firmware()
        org = self._get_org()
        self._create_administrator(organizations=[org])
        self._login(username="administrator", password="tester")
        url = reverse(
            f"admin:{self.config_app_label}_device_change", args=[device_fw.device_id]
        )
        r = self.client.get(url)
        self.assertContains(r, str(device_fw.image_id))

    def test_firmware_image_has_change_permission(self):
        request = MockRequest()
        request.user = User.objects.first()
        env = self._create_upgrade_env()
        self.assertIn(FirmwareImageInline, BuildAdmin.inlines)
        inline = FirmwareImageInline(FirmwareImage, admin.site)
        self.assertIsInstance(inline, FirmwareImageInline)
        self.assertIs(inline.has_change_permission(request), True)
        self.assertIs(inline.has_change_permission(request, obj=env["image1a"]), False)

    def test_firmware_image_inline_extraction_messages(self):
        self._login()
        dtb_message = "Target and Firmware version couldn't be extracted automatically"
        failed_message = "Automatic metadata extraction failed for this image"
        cases = (
            (
                "dtb_incomplete",
                FirmwareImage.STATUS_INCOMPLETE,
                "dtb",
                [dtb_message],
                [],
            ),
            (
                "fwtool_success",
                FirmwareImage.STATUS_SUCCESS,
                "fwtool",
                [],
                [dtb_message, failed_message],
            ),
            (
                "failed_extraction",
                FirmwareImage.STATUS_FAILED,
                "",
                [failed_message],
                [dtb_message],
            ),
        )
        for label, status, source, expected_present, expected_absent in cases:
            with self.subTest(label):
                build = self._create_build(version=f"0.1-{label}")
                image = self._create_firmware_image(build=build)
                update = {"extraction_status": status}
                if source:
                    update["source"] = source
                FirmwareImage.objects.filter(pk=image.pk).update(**update)
                url = reverse(f"admin:{self.app_label}_build_change", args=[build.pk])
                response = self.client.get(url)
                for message in expected_present:
                    self.assertContains(response, message)
                for message in expected_absent:
                    self.assertNotContains(response, message)

    def test_firmware_image_save_model_clears_compat_version_on_file_change(self):
        fw = self._create_firmware_image()
        FirmwareImage.objects.filter(pk=fw.pk).update(
            board="TP-Link WDR4300",
            compat_version="21.09",
            extraction_status=FirmwareImage.STATUS_SUCCESS,
        )
        fw.refresh_from_db()
        fw.file = self._get_simpleuploadedfile(self.FAKE_IMAGE_PATH2)
        request = MockRequest()
        request.user = User.objects.first()
        form = mock.MagicMock()
        form.changed_data = ["file"]
        fw_admin = FirmwareImageAdmin(FirmwareImage, admin.site)
        with mock.patch("django.db.transaction.on_commit"):
            fw_admin.save_model(request, fw, form, change=True)
        fw.refresh_from_db()
        self.assertEqual(fw.board, "")
        self.assertEqual(fw.compat_version, "")

    def test_firmware_image_save_model_dtb_no_flip_without_changed_fields(self):
        fw = self._create_firmware_image()
        FirmwareImage.objects.filter(pk=fw.pk).update(
            source="dtb",
            board="Orange Pi Zero",
            extraction_status=FirmwareImage.STATUS_INCOMPLETE,
        )
        fw.refresh_from_db()
        request = MockRequest()
        request.user = User.objects.first()
        form = mock.MagicMock()
        form.changed_data = ["board"]
        fw_admin = FirmwareImageAdmin(FirmwareImage, admin.site)
        with mock.patch("django.db.transaction.on_commit"):
            fw_admin.save_model(request, fw, form, change=True)
        fw.refresh_from_db()
        self.assertEqual(fw.extraction_status, FirmwareImage.STATUS_INCOMPLETE)

    def test_re_extract_metadata_action(self):
        self._login()
        image = self._create_firmware_image()
        FirmwareImage.objects.filter(pk=image.pk).update(
            extraction_status=FirmwareImage.STATUS_FAILED,
            failure_reason=FirmwareImage.FAILURE_UNSUPPORTED,
            extraction_log="log output",
            board="TP-Link WDR4300",
            compatible="tplink,tl-wdr4300-v1",
            target="ath79/generic",
            fw_version="23.05.5",
            compat_version="1.0",
            source="fwtool",
        )
        Build.objects.filter(pk=image.build_id).update(status=Build.BUILD_STATUS_FAILED)
        url = reverse(f"admin:{self.app_label}_firmwareimage_changelist")
        with mock.patch(
            "openwisp_firmware_upgrader.tasks.extract_firmware_metadata.delay"
        ) as mocked_delay:
            with self.captureOnCommitCallbacks(execute=True):
                r = self.client.post(
                    url,
                    {
                        "action": "re_extract_metadata",
                        ACTION_CHECKBOX_NAME: (str(image.pk),),
                    },
                    follow=True,
                )
        self.assertEqual(r.status_code, 200)
        image.refresh_from_db()
        self.assertEqual(image.extraction_status, FirmwareImage.STATUS_UNCONFIRMED)
        self.assertEqual(image.extraction_log, "")
        self.assertEqual(image.failure_reason, "")
        self.assertEqual(image.board, "")
        self.assertEqual(image.compatible, "")
        self.assertEqual(image.target, "")
        self.assertEqual(image.fw_version, "")
        self.assertEqual(image.compat_version, "")
        self.assertEqual(image.source, "")
        image.build.refresh_from_db()
        self.assertEqual(image.build.status, Build.BUILD_STATUS_ANALYZING)
        mocked_delay.assert_called_once_with(str(image.pk))

    def test_re_extract_metadata_action_multiple(self):
        self._login()
        build = self._create_build()
        image1 = self._create_firmware_image(build=build, type=self.TPLINK_4300_IMAGE)
        image2 = self._create_firmware_image(
            build=build, type=self.TPLINK_4300_IL_IMAGE
        )
        FirmwareImage.objects.filter(pk__in=[image1.pk, image2.pk]).update(
            extraction_status=FirmwareImage.STATUS_FAILED,
        )
        Build.objects.filter(pk=build.pk).update(status=Build.BUILD_STATUS_FAILED)
        url = reverse(f"admin:{self.app_label}_firmwareimage_changelist")
        with mock.patch(
            "openwisp_firmware_upgrader.tasks.extract_firmware_metadata.delay"
        ) as mocked_delay:
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(
                    url,
                    {
                        "action": "re_extract_metadata",
                        ACTION_CHECKBOX_NAME: (str(image1.pk), str(image2.pk)),
                    },
                    follow=True,
                )
        self.assertEqual(mocked_delay.call_count, 2)
        called_pks = {call.args[0] for call in mocked_delay.call_args_list}
        self.assertEqual(called_pks, {str(image1.pk), str(image2.pk)})
        image1.refresh_from_db()
        image2.refresh_from_db()
        self.assertEqual(image1.extraction_status, FirmwareImage.STATUS_UNCONFIRMED)
        self.assertEqual(image2.extraction_status, FirmwareImage.STATUS_UNCONFIRMED)
        build.refresh_from_db()
        self.assertEqual(build.status, Build.BUILD_STATUS_ANALYZING)

    def test_re_extract_metadata_action_skips_flashed_images(self):
        self._login()
        build = self._create_build()
        image_safe = self._create_firmware_image(
            build=build, type=self.TPLINK_4300_IMAGE
        )
        image_flashed = self._create_firmware_image(
            build=build, type=self.TPLINK_4300_IL_IMAGE
        )
        FirmwareImage.objects.filter(pk=image_safe.pk).update(
            extraction_status=FirmwareImage.STATUS_FAILED,
        )
        FirmwareImage.objects.filter(pk=image_flashed.pk).update(
            extraction_status=FirmwareImage.STATUS_SUCCESS
        )
        device = self._create_config(
            organization=image_flashed.build.category.organization
        ).device
        UpgradeOperation.objects.create(
            device=device, image=image_flashed, status="success"
        )
        url = reverse(f"admin:{self.app_label}_firmwareimage_changelist")
        with mock.patch(
            "openwisp_firmware_upgrader.tasks.extract_firmware_metadata.delay"
        ) as mocked_delay:
            with self.captureOnCommitCallbacks(execute=True):
                r = self.client.post(
                    url,
                    {
                        "action": "re_extract_metadata",
                        ACTION_CHECKBOX_NAME: (
                            str(image_safe.pk),
                            str(image_flashed.pk),
                        ),
                    },
                    follow=True,
                )
        self.assertEqual(r.status_code, 200)
        mocked_delay.assert_called_once_with(str(image_safe.pk))
        image_safe.refresh_from_db()
        self.assertEqual(image_safe.extraction_status, FirmwareImage.STATUS_UNCONFIRMED)
        image_flashed.refresh_from_db()
        self.assertEqual(image_flashed.extraction_status, FirmwareImage.STATUS_SUCCESS)
        self.assertContains(r, "1 image(s) were skipped")

    def test_re_extract_metadata_action_skips_state_machine_violations(self):
        self._login()
        build = self._create_build()

        with self.subTest("skips image with in-progress upgrade operation"):
            image_in_progress_upgrade = self._create_firmware_image(
                build=build, type=self.TPLINK_4300_IMAGE
            )
            FirmwareImage.objects.filter(pk=image_in_progress_upgrade.pk).update(
                extraction_status=FirmwareImage.STATUS_SUCCESS,
                board="TP-Link WDR4300",
            )
            image_in_progress_upgrade.refresh_from_db()
            device = self._create_config(
                organization=image_in_progress_upgrade.build.category.organization
            ).device
            UpgradeOperation.objects.create(
                device=device, image=image_in_progress_upgrade, status="in-progress"
            )
            url = reverse(f"admin:{self.app_label}_firmwareimage_changelist")
            with mock.patch(
                "openwisp_firmware_upgrader.tasks.extract_firmware_metadata.delay"
            ) as mocked_delay:
                with self.captureOnCommitCallbacks(execute=True):
                    self.client.post(
                        url,
                        {
                            "action": "re_extract_metadata",
                            ACTION_CHECKBOX_NAME: (str(image_in_progress_upgrade.pk),),
                        },
                        follow=True,
                    )
            mocked_delay.assert_not_called()
            image_in_progress_upgrade.refresh_from_db()
            self.assertEqual(
                image_in_progress_upgrade.extraction_status,
                FirmwareImage.STATUS_SUCCESS,
            )
            self.assertEqual(image_in_progress_upgrade.board, "TP-Link WDR4300")

        with self.subTest("reclaims image stuck in progress"):
            image_extracting = self._create_firmware_image(
                build=build, type=self.TPLINK_4300_IL_IMAGE
            )
            FirmwareImage.objects.filter(pk=image_extracting.pk).update(
                extraction_status=FirmwareImage.STATUS_IN_PROGRESS
            )
            url = reverse(f"admin:{self.app_label}_firmwareimage_changelist")
            with mock.patch(
                "openwisp_firmware_upgrader.tasks.extract_firmware_metadata.delay"
            ) as mocked_delay:
                with self.captureOnCommitCallbacks(execute=True):
                    self.client.post(
                        url,
                        {
                            "action": "re_extract_metadata",
                            ACTION_CHECKBOX_NAME: (str(image_extracting.pk),),
                        },
                        follow=True,
                    )
            mocked_delay.assert_called_once_with(str(image_extracting.pk))
            image_extracting.refresh_from_db()
            self.assertEqual(
                image_extracting.extraction_status, FirmwareImage.STATUS_UNCONFIRMED
            )

        with self.subTest("skips confirmed image and does not wipe its metadata"):
            confirmed_image = self._create_firmware_image(
                build=self._create_build(version="9.9")
            )
            FirmwareImage.objects.filter(pk=confirmed_image.pk).update(
                extraction_status=FirmwareImage.STATUS_MANUALLY_CONFIRMED,
                board="Generic x86",
                source="manual",
            )
            url = reverse(f"admin:{self.app_label}_firmwareimage_changelist")
            with mock.patch(
                "openwisp_firmware_upgrader.tasks.extract_firmware_metadata.delay"
            ) as mocked_delay:
                with self.captureOnCommitCallbacks(execute=True):
                    self.client.post(
                        url,
                        {
                            "action": "re_extract_metadata",
                            ACTION_CHECKBOX_NAME: (str(confirmed_image.pk),),
                        },
                        follow=True,
                    )
            mocked_delay.assert_not_called()
            confirmed_image.refresh_from_db()
            self.assertEqual(
                confirmed_image.extraction_status,
                FirmwareImage.STATUS_MANUALLY_CONFIRMED,
            )
            self.assertEqual(confirmed_image.board, "Generic x86")

        with self.subTest("skips successfully-extracted image"):
            success_image = self._create_firmware_image(
                build=self._create_build(version="8.8")
            )
            FirmwareImage.objects.filter(pk=success_image.pk).update(
                extraction_status=FirmwareImage.STATUS_SUCCESS,
                board="TP-Link WDR4300",
                source="fwtool",
            )
            url = reverse(f"admin:{self.app_label}_firmwareimage_changelist")
            with mock.patch(
                "openwisp_firmware_upgrader.tasks.extract_firmware_metadata.delay"
            ) as mocked_delay:
                with self.captureOnCommitCallbacks(execute=True):
                    self.client.post(
                        url,
                        {
                            "action": "re_extract_metadata",
                            ACTION_CHECKBOX_NAME: (str(success_image.pk),),
                        },
                        follow=True,
                    )
            mocked_delay.assert_not_called()
            success_image.refresh_from_db()
            self.assertEqual(
                success_image.extraction_status, FirmwareImage.STATUS_SUCCESS
            )
            self.assertEqual(success_image.board, "TP-Link WDR4300")

        with self.subTest("skips incomplete image and does not wipe its metadata"):
            incomplete_image = self._create_firmware_image(
                build=self._create_build(version="7.7")
            )
            FirmwareImage.objects.filter(pk=incomplete_image.pk).update(
                extraction_status=FirmwareImage.STATUS_INCOMPLETE,
                board="Xunlong Orange Pi Zero",
                source="dtb",
            )
            url = reverse(f"admin:{self.app_label}_firmwareimage_changelist")
            with mock.patch(
                "openwisp_firmware_upgrader.tasks.extract_firmware_metadata.delay"
            ) as mocked_delay:
                with self.captureOnCommitCallbacks(execute=True):
                    self.client.post(
                        url,
                        {
                            "action": "re_extract_metadata",
                            ACTION_CHECKBOX_NAME: (str(incomplete_image.pk),),
                        },
                        follow=True,
                    )
            mocked_delay.assert_not_called()
            incomplete_image.refresh_from_db()
            self.assertEqual(
                incomplete_image.extraction_status,
                FirmwareImage.STATUS_INCOMPLETE,
            )
            self.assertEqual(incomplete_image.board, "Xunlong Orange Pi Zero")

    def test_re_extract_metadata_action_skips_referenced_images(self):
        self._login()
        build = self._create_build()
        image = self._create_firmware_image(build=build, type=self.TPLINK_4300_IMAGE)
        FirmwareImage.objects.filter(pk=image.pk).update(
            extraction_status=FirmwareImage.STATUS_SUCCESS,
            board="TP-Link WDR4300",
            source="fwtool",
        )
        image.refresh_from_db()
        device = self._create_device_with_connection(
            organization=image.build.category.organization,
            model=image.board,
        )
        device_fw = DeviceFirmware.create_for_device(device, image)
        self.assertIsNotNone(device_fw)
        self.assertFalse(UpgradeOperation.objects.filter(image=image).exists())

        url = reverse(f"admin:{self.app_label}_firmwareimage_changelist")
        with mock.patch(
            "openwisp_firmware_upgrader.tasks.extract_firmware_metadata.delay"
        ) as mocked_delay:
            with self.captureOnCommitCallbacks(execute=True):
                r = self.client.post(
                    url,
                    {
                        "action": "re_extract_metadata",
                        ACTION_CHECKBOX_NAME: (str(image.pk),),
                    },
                    follow=True,
                )
        self.assertEqual(r.status_code, 200)
        mocked_delay.assert_not_called()
        image.refresh_from_db()
        self.assertEqual(image.extraction_status, FirmwareImage.STATUS_SUCCESS)
        self.assertEqual(image.board, "TP-Link WDR4300")
        self.assertContains(r, "1 image(s) were skipped")

    def test_device_firmware_inline_has_add_permission(self):
        device_fw = self._create_device_firmware()
        device = device_fw.device
        request = self.make_device_admin_request(device.pk)
        request.user = User.objects.first()
        inline = DeviceFirmwareInline(Device, admin.site)
        self.assertTrue(inline.has_add_permission(request, obj=None))
        self.assertTrue(inline.has_add_permission(request, obj=device))
        self.assertIsInstance(inline, DeviceFirmwareInline)
        deviceadmin = DeviceAdmin(model=Device, admin_site=admin.site)
        self.assertIn(
            DeviceFirmwareInline, deviceadmin.get_inlines(request, obj=device)
        )

    def test_device_firmware_inline(self):
        device_fw = self._create_device_firmware()
        device = device_fw.device
        request = self.make_device_admin_request(device.pk)
        request.user = User.objects.first()
        deviceadmin = DeviceAdmin(model=Device, admin_site=admin.site)
        self.assertNotIn(
            DeviceFirmwareInline, deviceadmin.get_inlines(request, obj=None)
        )
        self.assertIn(
            DeviceFirmwareInline, deviceadmin.get_inlines(request, obj=device)
        )

    def test_device_firmware_inline_target_and_fw_version_display(self):
        self._login()
        device_fw = self._create_device_firmware()
        url = reverse(
            f"admin:{self.config_app_label}_device_change", args=[device_fw.device.pk]
        )
        with self.subTest("shows values when populated"):
            FirmwareImage.objects.filter(pk=device_fw.image.pk).update(
                extraction_status=FirmwareImage.STATUS_SUCCESS,
                target="ath79/generic",
                fw_version="23.05.5",
            )
            response = self.client.get(url)
            self.assertContains(response, "ath79/generic")
            self.assertContains(response, "23.05.5")

        with self.subTest("shows dash when empty"):
            FirmwareImage.objects.filter(pk=device_fw.image.pk).update(
                target="", fw_version=""
            )
            response = self.client.get(url)
            content = response.content.decode()
            self.assertEqual(
                self._get_readonly_field_value(content, "image_target_display"), "-"
            )
            self.assertEqual(
                self._get_readonly_field_value(content, "image_fw_version_display"),
                "-",
            )

    def _prepare_image_qs_test_env(self):
        device_fw = self._create_device_firmware()
        device = device_fw.device
        request = self.make_device_admin_request(device.pk)
        request.user = User.objects.first()
        org2 = self._create_org(name="org2", slug="org2")
        category_org2 = self._create_category(organization=org2, name="org2")
        build_org2 = self._create_build(category=category_org2)
        img_org2 = self._create_firmware_image(build=build_org2)
        yuncore = self._create_firmware_image(
            build=device_fw.image.build,
            type="ar71xx-generic-xd3200-squashfs.sysupgrade.bin",
        )
        mesh_category = self._create_category(
            name="mesh", organization=device.organization
        )
        mesh_build = self._create_build(category=mesh_category)
        mesh_image = self._create_firmware_image(build=mesh_build)
        return device, device_fw, img_org2, yuncore, mesh_image

    def test_image_queryset_existing_device_firmware(self):
        (
            device,
            device_fw,
            img_org2,
            yuncore,
            mesh_image,
        ) = self._prepare_image_qs_test_env()
        # existing DeviceFirmware
        # restricts images to category of image in used
        form = DeviceFirmwareForm(device=device, instance=device_fw)
        self.assertEqual(form.fields["image"].queryset.count(), 1)
        self.assertIn(device_fw.image, form.fields["image"].queryset)
        self.assertNotIn(img_org2, form.fields["image"].queryset)

    def test_image_queryset_new_device_firmware(self):
        (
            device,
            device_fw,
            img_org2,
            yuncore,
            mesh_image,
        ) = self._prepare_image_qs_test_env()
        # new DeviceFirmware
        # shows all the categories related to the model
        form = DeviceFirmwareForm(device=device)
        self.assertEqual(form.fields["image"].queryset.count(), 2)
        self.assertIn(device_fw.image, form.fields["image"].queryset)
        self.assertIn(mesh_image, form.fields["image"].queryset)
        self.assertNotIn(img_org2, form.fields["image"].queryset)

    def test_image_queryset_no_model(self):
        (
            device,
            device_fw,
            img_org2,
            yuncore,
            mesh_image,
        ) = self._prepare_image_qs_test_env()
        # existing DeviceFirmware
        # if no model specified, get all models available
        device.model = ""
        device.save()
        form = DeviceFirmwareForm(device=device, instance=device_fw)
        self.assertEqual(form.fields["image"].queryset.count(), 2)
        self.assertIn(yuncore, form.fields["image"].queryset)
        self.assertNotIn(img_org2, form.fields["image"].queryset)

    def test_image_queryset_no_model_nor_device_firmware(self):
        (
            device,
            device_fw,
            img_org2,
            yuncore,
            mesh_image,
        ) = self._prepare_image_qs_test_env()
        # new DeviceFirmware, no model
        # returns all devices of the org
        device.model = ""
        device.save()
        form = DeviceFirmwareForm(device=device)
        self.assertEqual(form.fields["image"].queryset.count(), 3)
        self.assertIn(device_fw.image, form.fields["image"].queryset)
        self.assertIn(mesh_image, form.fields["image"].queryset)
        self.assertIn(yuncore, form.fields["image"].queryset)
        self.assertNotIn(img_org2, form.fields["image"].queryset)

    def test_image_queryset_shared_firmware(self):
        (
            device,
            device_fw,
            _,
            _,
            _,
        ) = self._prepare_image_qs_test_env()
        shared_image = self._create_firmware_image(
            build=self._create_build(
                category=self._create_category(organization=None, name="Shared")
            )
        )
        form = DeviceFirmwareForm(device=device)
        self.assertEqual(form.fields["image"].queryset.count(), 3)
        self.assertIn(device_fw.image, form.fields["image"].queryset)
        self.assertIn(shared_image, form.fields["image"].queryset)

    def test_device_firmware_form_image_dropdown_shows_board(self):
        self._login()
        device_fw = self._create_device_firmware()
        device = device_fw.device
        url = reverse(f"admin:{self.config_app_label}_device_change", args=[device.pk])
        response = self.client.get(url)
        expected_label = f"{device_fw.image.build}: {device_fw.image.board}"
        self.assertContains(response, expected_label)

    def test_device_firmware_form_image_dropdown_distinguishes_by_type(self):
        self._login()
        device_fw = self._create_device_firmware()
        device = device_fw.device
        second_image = self._create_firmware_image(
            build=device_fw.image.build,
            type="ar71xx-generic-cpe210-220-v1-squashfs-factory.bin",
        )
        FirmwareImage.objects.filter(pk=second_image.pk).update(
            board=device_fw.image.board,
            fw_version=device_fw.image.fw_version,
            extraction_status=FirmwareImage.STATUS_MANUALLY_CONFIRMED,
        )
        url = reverse(f"admin:{self.config_app_label}_device_change", args=[device.pk])
        response = self.client.get(url)
        self.assertContains(response, f"[{device_fw.image.type}]")
        self.assertContains(response, f"[{second_image.type}]")

    def test_admin_menu_groups(self):
        # Test menu group (openwisp-utils menu group) for Build, Category,
        # BatchUpgradeOperation models
        self._login()
        models = ["build", "category", "batchupgradeoperation"]
        response = self.client.get(reverse("admin:index"))
        for model in models:
            with self.subTest(f"test menu group link {model} model"):
                url = reverse(f"admin:{self.app_label}_{model}_changelist")
                self.assertContains(response, f'class="mg-link" href="{url}"')
        with self.subTest("test firmware group is registered"):
            self.assertContains(
                response,
                '<div class="mg-dropdown-label">Firmware </div>',
                html=True,
            )

    def test_save_device_with_deleted_devicefirmware(self):
        self._login()
        device_fw = self._create_device_firmware()
        device = device_fw.device
        device_conn = device.deviceconnection_set.first()
        device_params = self._get_device_params(
            device, device_conn, device_fw.image, device_fw
        )
        FirmwareImage.objects.all().delete()
        response = self.client.post(
            reverse(f"admin:{self.config_app_label}_device_change", args=[device.id]),
            data=device_params,
            follow=True,
        )
        self.assertEqual(response.status_code, 200)

    @capture_stderr()
    @mock.patch(
        "openwisp_firmware_upgrader.utils.get_upgrader_class_from_device_connection"
    )
    def test_device_firmware_upgrade_without_device_connection(
        self, captured_stderr, mocked_func
    ):
        self._login()
        device_fw = self._create_device_firmware()
        device = device_fw.device
        device.deviceconnection_set.all().delete()
        response = self.client.get(
            reverse(f"admin:{self.config_app_label}_device_change", args=[device.id])
        )
        self.assertNotIn(
            "'NoneType' object has no attribute 'update_strategy'",
            captured_stderr.getvalue(),
        )
        mocked_func.assert_not_called()
        self.assertEqual(response.status_code, 200)

    def test_save_device_after_credentials_deleted(self):
        """Regression test for #250."""
        self._login()
        device_fw = self._create_device_firmware(installed=True)
        device = device_fw.device
        device_conn = device.deviceconnection_set.first()
        device_params = self._get_device_params(
            device, device_conn, device_fw.image, device_fw
        )
        device.deviceconnection_set.all().delete()
        device_params["deviceconnection_set-TOTAL_FORMS"] = 0
        device_params["deviceconnection_set-INITIAL_FORMS"] = 0
        del device_params["deviceconnection_set-0-credentials"]
        del device_params["deviceconnection_set-0-id"]
        del device_params["deviceconnection_set-0-update_strategy"]
        del device_params["deviceconnection_set-0-enabled"]
        response = self.client.post(
            reverse(f"admin:{self.config_app_label}_device_change", args=[device.id]),
            data=device_params,
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Please correct the error")

    def test_change_image_and_add_credentials_together(self):
        """Regression test for #250."""
        self._login()
        device_fw = self._create_device_firmware()
        device = device_fw.device
        device_conn = device.deviceconnection_set.first()
        credentials_id = device_conn.credentials_id
        update_strategy = device_conn.update_strategy
        # create a new image to switch to
        build = self._create_build(version="0.2")
        new_image = self._create_firmware_image(build=build)
        # delete existing connection
        device.deviceconnection_set.all().delete()
        # build form data: new image + new credentials in same submit
        device_params = self._get_device_params(
            device, device_conn, new_image, device_fw
        )
        device_params.update(
            {
                "devicefirmware-0-image": str(new_image.id),
                "deviceconnection_set-TOTAL_FORMS": 1,
                "deviceconnection_set-INITIAL_FORMS": 0,
                "deviceconnection_set-0-credentials": str(credentials_id),
                "deviceconnection_set-0-update_strategy": update_strategy,
                "deviceconnection_set-0-enabled": True,
            }
        )
        # `_get_device_params` populated `-0-id` from the now-deleted connection;
        # with INITIAL_FORMS=0 the formset must treat row 0 as new, not as an edit.
        del device_params["deviceconnection_set-0-id"]
        response = self.client.post(
            reverse(f"admin:{self.config_app_label}_device_change", args=[device.id]),
            data=device_params,
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Please correct the error")
        device_fw.refresh_from_db()
        self.assertEqual(device_fw.image, new_image)
        self.assertEqual(device.deviceconnection_set.count(), 1)

    def test_add_credentials_with_cancelled_upgrade_operation(self):
        """Regression test for adding credentials while a cancelled upgrade is shown."""
        with mock.patch(self._mock_connect, return_value=True), mock.patch(
            self._mock_upgrade, return_value=True
        ):
            self._login()
            device = self._create_config(organization=self._get_org()).device
            device_conn = self._create_device_connection(device=device)
            credentials_id = device_conn.credentials_id
            update_strategy = device_conn.update_strategy
            image = self._create_firmware_image(organization=device.organization)
            device_params = self._get_device_params(
                device,
                device_conn,
                image,
                upgrade_options=json.dumps({"c": True}),
            )
            response = self.client.post(
                reverse(
                    f"admin:{self.config_app_label}_device_change", args=[device.id]
                ),
                data=device_params,
                follow=True,
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(device.upgradeoperation_set.count(), 1)
            # cancel upgrade operation and remove DeviceConnection object
            upgrade_operation = device.upgradeoperation_set.get()
            upgrade_operation.cancel()
            device_fw = device.devicefirmware
            device.deviceconnection_set.all().delete()
            # submit form creating a new credential
            device_params = self._get_device_params(
                device, device_conn, image, device_fw
            )
            device_params.update(
                {
                    "deviceconnection_set-TOTAL_FORMS": 1,
                    "deviceconnection_set-INITIAL_FORMS": 0,
                    "deviceconnection_set-0-credentials": str(credentials_id),
                    "deviceconnection_set-0-update_strategy": update_strategy,
                    "deviceconnection_set-0-enabled": True,
                    "upgradeoperation_set-TOTAL_FORMS": 1,
                    "upgradeoperation_set-INITIAL_FORMS": 1,
                    "upgradeoperation_set-0-id": str(upgrade_operation.id),
                    "upgradeoperation_set-0-device": str(device.id),
                }
            )
            del device_params["deviceconnection_set-0-id"]
            response = self.client.post(
                reverse(
                    f"admin:{self.config_app_label}_device_change", args=[device.id]
                ),
                data=device_params,
                follow=True,
            )
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(
                response, "No related connection or credentials found for this device."
            )
            self.assertEqual(device.deviceconnection_set.count(), 1)

    def test_deactivated_firmware_image_inline(self):
        self._login()
        device = self._create_config(organization=self._get_org()).device
        self._create_device_firmware(device=device)
        device.deactivate()
        response = self.client.get(
            reverse(f"admin:{self.config_app_label}_device_change", args=[device.id])
        )
        # Check that it is not possible to add a DeviceFirmwareImage to a
        # deactivated device in the admin interface.
        self.assertContains(
            response,
            '<input type="hidden" name="devicefirmware-MAX_NUM_FORMS"'
            ' value="0" id="id_devicefirmware-MAX_NUM_FORMS">',
        )
        # Ensure that a deactivated device's existing DeviceFirmwareImage
        # is displayed as readonly in the admin interface.
        self.assertContains(
            response,
            f"Test Category v0.1: {self.TPLINK_4300_IMAGE}",
        )
        self.assertNotContains(
            response,
            '<select name="devicefirmware-0-image" id="id_devicefirmware-0-image">',
        )

    def test_deactivated_device_upgrade_operation_readonly(self):
        self._login()
        device = self._create_config(organization=self._get_org()).device
        device.deactivate()
        operation = UpgradeOperation.objects.create(device=device, status="failed")
        response = self.client.get(
            reverse(f"admin:{self.config_app_label}_device_change", args=[device.id])
        )
        self.assertContains(response, str(operation.pk))
        # deactivated devices are readonly
        self.assertNotContains(response, 'name="upgradeoperation_set-0-DELETE"')

    def test_device_upgrade_shared_firmware(self):
        org = self._get_org()
        administrator = self._create_administrator(organizations=[org])
        shared_image = self._create_firmware_image(organization=None)
        device = self._create_device_with_connection()
        device_conn = device.deviceconnection_set.first()
        device_params = self._get_device_params(device, device_conn, shared_image)
        path = reverse(f"admin:{self.config_app_label}_device_change", args=[device.id])

        with self.subTest("Test with administrator account"):
            self.client.force_login(administrator)
            response = self.client.post(
                path,
                data=device_params,
                follow=True,
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(device.upgradeoperation_set.count(), 1)
            self.assertEqual(
                DeviceFirmware.objects.filter(
                    image=shared_image, device=device
                ).count(),
                1,
            )

        DeviceFirmware.objects.all().delete()
        self.client.logout()
        with self.subTest("Test with superuser account"):
            self._login()
            response = self.client.post(
                path,
                data=device_params,
                follow=True,
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(device.upgradeoperation_set.count(), 2)
            self.assertEqual(
                DeviceFirmware.objects.filter(
                    image=shared_image, device=device
                ).count(),
                1,
            )

    def test_admin_multitenancy(self):
        shared_category = self._get_category(name="Shared", organization=None)
        shared_build = self._create_build(category=shared_category, version="0.1")
        org = self._get_org()
        org_category = self._get_category(name="Org", organization=org)
        org_build = self._create_build(category=org_category, version="0.2")
        self._create_administrator(organizations=[org])
        self._test_multitenant_admin(
            reverse(f"admin:{self.app_label}_category_changelist"),
            visible=[
                '<a href="{}">{}</a>'.format(
                    reverse(
                        f"admin:{self.app_label}_category_change",
                        args=[org_category.pk],
                    ),
                    org_category.name,
                )
            ],
            hidden=[
                '<a href="{}">{}</a>'.format(
                    reverse(
                        f"admin:{self.app_label}_category_change",
                        args=[shared_category.pk],
                    ),
                    shared_category.name,
                )
            ],
            administrator=True,
        )
        self._test_multitenant_admin(
            self.build_list_url,
            visible=[
                '<a href="{}">{}</a>'.format(
                    reverse(
                        f"admin:{self.app_label}_build_change", args=[org_build.pk]
                    ),
                    str(org_build),
                )
            ],
            hidden=[
                '<a href="{}">{}</a>'.format(
                    reverse(
                        f"admin:{self.app_label}_build_change", args=[shared_build.pk]
                    ),
                    str(shared_build),
                )
            ],
            administrator=True,
        )

    def test_firmware_image_build_readonly_for_organization_admin(self):
        org = self._get_org()
        image = self._create_firmware_image(organization=org)
        original_build_id = image.build_id
        other_build = self._create_build(category=image.build.category, version="99.0")
        administrator = self._create_administrator(organizations=[org])
        self.client.force_login(administrator)
        url = reverse(f"admin:{self.app_label}_firmwareimage_change", args=[image.pk])

        with self.subTest("build field is rendered read-only"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, '<select name="build"')

        with self.subTest("posting a different build is ignored"):
            data = {"build": str(other_build.pk), "_save": "Save"}
            response = self.client.post(url, data, follow=True)
            self.assertNotContains(
                response,
                "errorlist",
                msg_prefix="form should be valid so read-only handling is exercised",
            )
            image.refresh_from_db()
            self.assertEqual(image.build_id, original_build_id)

    def test_firmware_image_admin_multitenancy(self):
        org1 = self._get_org()
        org2 = self._create_org(name="Org 2", slug="org2")
        image1 = self._create_firmware_image(organization=org1)
        image2 = self._create_firmware_image(organization=org2)
        administrator = self._create_administrator(organizations=[org1])
        image1_url = reverse(
            f"admin:{self.app_label}_firmwareimage_change", args=[image1.pk]
        )
        image2_url = reverse(
            f"admin:{self.app_label}_firmwareimage_change", args=[image2.pk]
        )
        self.client.force_login(administrator)

        with self.subTest("changelist only shows managed organization images"):
            response = self.client.get(
                reverse(f"admin:{self.app_label}_firmwareimage_changelist")
            )
            self.assertContains(
                response,
                image1_url,
                msg_prefix="Firmware image multi-tenancy test failed",
            )
            self.assertNotContains(
                response,
                image2_url,
                msg_prefix="Firmware image multi-tenancy test failed",
            )

        with self.subTest("change view denies another organization image"):
            response = self.client.get(image2_url, follow=True)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.request["PATH_INFO"],
                reverse("admin:index"),
                "Firmware image multi-tenancy test failed",
            )

        with self.subTest("add form build choices exclude other organization builds"):
            org2_build = self._create_build(
                category=self._create_category(
                    name="Org2 Multitenancy Category", organization=org2
                ),
                version="1.0",
            )
            add_url = reverse(f"admin:{self.app_label}_firmwareimage_add")
            response = self.client.get(add_url)
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(
                response,
                f'<option value="{org2_build.pk}"',
                msg_prefix="Firmware image multi-tenancy test failed",
            )

        with self.subTest("add form build choices exclude shared builds"):
            shared_build = self._create_build(
                category=self._create_category(
                    name="Shared Multitenancy Category", organization=None
                ),
                version="2.0",
            )
            add_url = reverse(f"admin:{self.app_label}_firmwareimage_add")
            response = self.client.get(add_url)
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(
                response,
                f'<option value="{shared_build.pk}"',
                msg_prefix="Firmware image multi-tenancy test failed",
            )

        with self.subTest("posting a shared build as non-superuser is rejected"):
            data = {
                "build": str(shared_build.pk),
                "file": self._get_simpleuploadedfile(self.FAKE_IMAGE_PATH2),
                "type": self.TPLINK_4300_IMAGE,
                "_save": "Save",
            }
            response = self.client.post(add_url, data)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "errorlist")
            self.assertFalse(FirmwareImage.objects.filter(build=shared_build).exists())

    def test_empty_device_firmware_image(self):
        self._login()
        device = self._create_device_with_connection()
        device_conn = device.deviceconnection_set.first()
        fw_image = self._create_firmware_image()
        url = reverse(f"admin:{self.config_app_label}_device_change", args=[device.id])
        data = self._get_device_params(device, device_conn, fw_image=fw_image)
        data.update(
            {
                "devicefirmware-0-image": "",
                "devicefirmware-TOTAL_FORMS": 1,
                "devicefirmware-INITIAL_FORMS": 0,
            }
        )
        response = self.client.post(url, data, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="errorlist"')
        self.assertContains(response, "This field is required.")
        self.assertFalse(DeviceFirmware.objects.filter(device=device).exists())

    def test_batch_upgrade_operation_detail_organization_filter(self):
        category = self._create_category(name="Shared", organization=None)
        env = self._create_upgrade_env(category=category)
        org1 = env["d1"].organization
        org2 = self._create_org(name="org2", slug="org2")
        org1_admin = self._create_administrator(organizations=[org1])
        batch = env["build2"].batch_upgrade(firmwareless=True)
        url = reverse(
            f"admin:{self.app_label}_batchupgradeoperation_change", args=[batch.pk]
        )

        def _get_org_option(org):
            return f'<a title="{org.name}" href="?organization={org.id}">{org.name}</a>'

        org1_option = _get_org_option(org1)
        org2_option = _get_org_option(org2)
        with self.subTest(
            "Superuser: Organization filter is visible for shared category"
        ):
            self._login()
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "By organization")
            self.assertContains(
                response,
                org1_option,
                html=True,
            )
            self.assertContains(
                response,
                org2_option,
                html=True,
            )

        with self.subTest("Org admin: Cannot view shared mass upgrade operation"):
            self.client.force_login(org1_admin)
            response = self.client.get(url, follow=True)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.request["PATH_INFO"], reverse("admin:index"))
            self.assertContains(
                response,
                f'<li class="warning">Mass upgrade operation with ID “{batch.pk}”'
                " doesn’t exist. Perhaps it was deleted?</li>",
                html=True,
            )

        env["category"].organization = org1
        env["category"].save()
        with self.subTest(
            "Superuser: Organization filter hidden when category belongs to org"
        ):
            self._login()
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, "By organization")

        with self.subTest(
            "Org admin: Organization filter hidden when category belongs to org"
        ):
            self.client.force_login(org1_admin)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, "By organization")

    def test_batch_upgrade_operation_filters(self):
        """Test that filter UI elements are displayed correctly for organization admin"""
        env = self._create_upgrade_env()
        org_admin = self._create_administrator(organizations=[env["d1"].organization])
        self.client.force_login(org_admin)
        batch = env["build2"].batch_upgrade(firmwareless=True)
        url = reverse(
            f"admin:{self.app_label}_batchupgradeoperation_change", args=[batch.pk]
        )

        with self.subTest("Test filter UI elements are present"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            # Check status filter options
            self.assertContains(response, "By status")
            self.assertContains(response, 'title="in progress"')
            self.assertContains(response, 'title="success"')
            self.assertContains(response, 'title="failed"')
            # Organization filter should not be present because the build's category is not shared
            self.assertNotContains(response, "By organization")

        with self.subTest("Test active filter indication"):
            # Test with status filter active
            response = self.client.get(url + "?status=in-progress")
            self.assertEqual(response.status_code, 200)
            # Check that the in-progress status is selected
            self.assertContains(
                response,
                (
                    '<a class="selected" title="in progress" href="?status=in-progress">'
                    "in progress</a>"
                ),
                html=True,
            )

        with self.subTest("Filter link building preserves other GET params"):
            # Apply search and status simultaneously and verify the generated
            # "All" choice keeps the search parameter when building its
            # query string. The href for the idle option will still contain
            # both params, but the important part is the all link.
            response = self.client.get(url + "?q=testsearch&status=idle")
            self.assertEqual(response.status_code, 200)
            content = response.content.decode()
            self.assertIn('href="?q=testsearch"', content)
            self.assertContains(
                response,
                '<a title="All" href="?q=testsearch">All</a>',
                html=True,
            )

    def _get_device_upgrade_operation_delete_params(
        self, device, device_conn, device_fw, operation
    ):
        params = self._get_device_params(
            device, device_conn, device_fw.image, device_fw
        )
        params.update(
            {
                "upgradeoperation_set-TOTAL_FORMS": 1,
                "upgradeoperation_set-INITIAL_FORMS": 1,
                "upgradeoperation_set-MIN_NUM_FORMS": 0,
                "upgradeoperation_set-MAX_NUM_FORMS": 0,
                "upgradeoperation_set-0-id": str(operation.pk),
                "upgradeoperation_set-0-DELETE": "on",
            }
        )
        return params

    def _get_input_tag(self, content, name):
        match = re.search(rf'<input\b[^>]*\bname="{re.escape(name)}"[^>]*>', content)
        if not match:
            raise ValueError(f'Input with name="{name}" not found')
        return match.group(0)

    def _get_readonly_field_value(self, content, field_name):
        match = re.search(
            rf"field-{re.escape(field_name)}\b[\s\S]*?"
            r'<div class="readonly">([^<]*)</div>',
            content,
        )
        if not match:
            raise ValueError(f'Readonly field "{field_name}" not found')
        return match.group(1)

    def test_device_bulk_delete_with_upgrade_operation(self):
        self._login()
        org = self._create_org(name="bulk-delete-org", slug="bulk-delete-org")
        device = self._create_device_with_connection(organization=org)
        device.deactivate()
        device.config.set_status_deactivated()
        operation = UpgradeOperation.objects.create(device=device)
        changelist_url = reverse(f"admin:{self.config_app_label}_device_changelist")
        payload = {
            "action": "delete_selected",
            ACTION_CHECKBOX_NAME: [str(device.pk)],
        }

        with self.subTest("in-progress operation blocks device bulk delete"):
            response = self.client.post(changelist_url, data=payload)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Cannot delete Device")
            self.assertContains(response, "upgrade operation")
            self.assertIn("upgrade operation", response.context["perms_lacking"])
            self.assertTrue(Device.objects.filter(pk=device.pk).exists())
            self.assertTrue(UpgradeOperation.objects.filter(pk=operation.pk).exists())

        with self.subTest("failed operation allows device bulk delete"):
            operation.status = "failed"
            operation.save(update_fields=["status"])
            response = self.client.post(changelist_url, data=payload)
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, "Cannot delete")
            self.assertNotContains(response, "upgrade operation")
            self.assertEqual(response.context["perms_lacking"], set())
            payload["post"] = "yes"
            response = self.client.post(changelist_url, data=payload, follow=True)
            self.assertEqual(response.status_code, 200)
            self.assertFalse(Device.objects.filter(pk=device.pk).exists())
            self.assertFalse(UpgradeOperation.objects.filter(pk=operation.pk).exists())

    def test_upgrade_operation_admin_delete_selected_action_present(self):
        self._login()
        device = self._create_device_with_connection()
        UpgradeOperation.objects.create(device=device, status="failed")
        url = reverse(f"admin:{self.app_label}_upgradeoperation_changelist")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<option value="delete_selected">')

    def test_upgrade_operation_admin_delete_by_status(self):
        self._login()
        device = self._create_device_with_connection()
        operation = UpgradeOperation.objects.create(device=device)
        change_url = reverse(
            f"admin:{self.app_label}_upgradeoperation_change", args=[operation.pk]
        )
        delete_url = reverse(
            f"admin:{self.app_label}_upgradeoperation_delete", args=[operation.pk]
        )

        with self.subTest("in-progress operation does not show delete button"):
            response = self.client.get(change_url)
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, delete_url)

        with self.subTest("failed operation can be deleted"):
            operation.status = "failed"
            operation.save(update_fields=["status"])
            response = self.client.get(change_url)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, delete_url)
            response = self.client.post(delete_url, {"post": "yes"}, follow=True)
            self.assertEqual(response.status_code, 200)
            self.assertFalse(UpgradeOperation.objects.filter(pk=operation.pk).exists())

    def test_upgrade_operation_admin_bulk_delete_in_progress_not_allowed(self):
        self._login()
        device = self._create_device_with_connection()
        operation = UpgradeOperation.objects.create(device=device)
        failed_operation = UpgradeOperation.objects.create(
            device=device, status="failed"
        )
        url = reverse(f"admin:{self.app_label}_upgradeoperation_changelist")
        response = self.client.post(
            url,
            data={
                "action": "delete_selected",
                ACTION_CHECKBOX_NAME: [str(operation.pk), str(failed_operation.pk)],
                "post": "yes",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Some selected operations are still in progress and cannot be deleted. "
            "Remove them from the selection and try again.",
        )
        self.assertTrue(UpgradeOperation.objects.filter(pk=operation.pk).exists())
        self.assertTrue(
            UpgradeOperation.objects.filter(pk=failed_operation.pk).exists()
        )

    def test_batch_upgrade_operation_admin_delete_selected_action_present(self):
        self._login()
        build = self._create_build()
        BatchUpgradeOperation.objects.create(build=build, status="failed")
        url = reverse(f"admin:{self.app_label}_batchupgradeoperation_changelist")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<option value="delete_selected">')

    def test_batch_upgrade_operation_admin_delete_by_status(self):
        self._login()
        build = self._create_build()
        batch = BatchUpgradeOperation.objects.create(build=build, status="in-progress")
        change_url = reverse(
            f"admin:{self.app_label}_batchupgradeoperation_change", args=[batch.pk]
        )
        delete_url = reverse(
            f"admin:{self.app_label}_batchupgradeoperation_delete", args=[batch.pk]
        )

        with self.subTest("in-progress batch does not show delete button"):
            response = self.client.get(change_url)
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, delete_url)

        with self.subTest("failed batch can be deleted"):
            batch.status = "failed"
            batch.save(update_fields=["status"])
            response = self.client.get(change_url)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, delete_url)
            response = self.client.post(delete_url, {"post": "yes"}, follow=True)
            self.assertEqual(response.status_code, 200)
            self.assertFalse(BatchUpgradeOperation.objects.filter(pk=batch.pk).exists())

    def test_batch_upgrade_operation_admin_bulk_delete_by_status(self):
        self._login()
        org = self._get_org()
        build = self._create_build(category=self._create_category(organization=org))
        batch = BatchUpgradeOperation.objects.create(build=build, status="in-progress")
        device = self._create_device_with_connection(organization=org)
        operation = UpgradeOperation.objects.create(device=device, batch=batch)
        url = reverse(f"admin:{self.app_label}_batchupgradeoperation_changelist")
        payload = {
            "action": "delete_selected",
            ACTION_CHECKBOX_NAME: [str(batch.pk)],
        }

        with self.subTest("in-progress batch cannot be deleted"):
            failed_batch = BatchUpgradeOperation.objects.create(
                build=build, status="failed"
            )
            payload[ACTION_CHECKBOX_NAME].append(str(failed_batch.pk))
            payload["post"] = "yes"
            response = self.client.post(url, data=payload, follow=True)
            self.assertEqual(response.status_code, 200)
            self.assertContains(
                response,
                "Some selected operations are still in progress and cannot be deleted. "
                "Remove them from the selection and try again.",
            )
            self.assertTrue(BatchUpgradeOperation.objects.filter(pk=batch.pk).exists())
            self.assertTrue(
                BatchUpgradeOperation.objects.filter(pk=failed_batch.pk).exists()
            )
            self.assertTrue(UpgradeOperation.objects.filter(pk=operation.pk).exists())
            payload[ACTION_CHECKBOX_NAME].remove(str(failed_batch.pk))
            payload.pop("post")
            failed_batch.delete()

        with self.subTest("failed batch can be deleted"):
            operation.status = "failed"
            operation.save(update_fields=["status"])
            batch.refresh_from_db()
            self.assertEqual(batch.status, "failed")
            response = self.client.post(url, data=payload)
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, "Cannot delete")
            payload["post"] = "yes"
            response = self.client.post(url, data=payload, follow=True)
            self.assertEqual(response.status_code, 200)
            self.assertFalse(BatchUpgradeOperation.objects.filter(pk=batch.pk).exists())
            self.assertFalse(UpgradeOperation.objects.filter(pk=operation.pk).exists())

    def test_device_upgrade_operation_inline_delete_by_status(self):
        self._login()
        device = self._create_device_with_connection()
        device_conn = device.deviceconnection_set.first()
        device_fw = self._create_device_firmware(device=device, device_connection=False)
        operation = UpgradeOperation.objects.create(device=device)
        url = reverse(f"admin:{self.config_app_label}_device_change", args=[device.pk])

        with self.subTest("in-progress operation cannot be deleted inline"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            delete_input = self._get_input_tag(
                response.content.decode(), "upgradeoperation_set-0-DELETE"
            )
            self.assertIn("disabled", delete_input)
            response = self.client.post(
                url,
                data=self._get_device_upgrade_operation_delete_params(
                    device, device_conn, device_fw, operation
                ),
                follow=True,
            )
            self.assertEqual(response.status_code, 200)
            self.assertTrue(UpgradeOperation.objects.filter(pk=operation.pk).exists())

        with self.subTest("failed operation can be deleted inline"):
            operation.status = "failed"
            operation.save(update_fields=["status"])
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'name="upgradeoperation_set-0-DELETE"')
            response = self.client.post(
                url,
                data=self._get_device_upgrade_operation_delete_params(
                    device, device_conn, device_fw, operation
                ),
                follow=True,
            )
            self.assertEqual(response.status_code, 200)
            self.assertFalse(UpgradeOperation.objects.filter(pk=operation.pk).exists())

    def test_device_upgrade_operation_inline_delete_mixed_statuses(self):
        self._login()
        device = self._create_device_with_connection()
        self._create_device_firmware(device=device, device_connection=False)
        in_progress_operation = UpgradeOperation.objects.create(device=device)
        failed_operation = UpgradeOperation.objects.create(
            device=device, status="failed"
        )
        url = reverse(f"admin:{self.config_app_label}_device_change", args=[device.pk])
        response = self.client.get(url)
        content = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn(f'value="{failed_operation.pk}"', content)
        self.assertIn(f'value="{in_progress_operation.pk}"', content)
        failed_index = content.index(f'value="{failed_operation.pk}"')
        in_progress_index = content.index(f'value="{in_progress_operation.pk}"')
        failed_delete_input = self._get_input_tag(
            content, "upgradeoperation_set-0-DELETE"
        )
        in_progress_delete_input = self._get_input_tag(
            content, "upgradeoperation_set-1-DELETE"
        )
        self.assertNotIn("disabled", failed_delete_input)
        self.assertIn("disabled", in_progress_delete_input)
        self.assertLess(failed_index, in_progress_index)

    def test_upgrade_operation_change_view_api_disabled(self):
        self._login()
        device = self._create_device_with_connection()
        operation = UpgradeOperation.objects.create(device=device)
        change_url = reverse(
            f"admin:{self.app_label}_upgradeoperation_change", args=[operation.pk]
        )
        with mock.patch.object(app_settings, "FIRMWARE_UPGRADER_API", False):
            response = self.client.get(change_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context.get("upgrade_operation_cancel_url"), "")
        self.assertContains(response, 'var owUpgradeOperationCancelUrl = "";')

    def test_device_change_page_api_disabled(self):
        self._login()
        device_fw = self._create_device_firmware()
        device = device_fw.device
        change_url = reverse(
            f"admin:{self.config_app_label}_device_change", args=[device.pk]
        )
        with mock.patch.object(app_settings, "FIRMWARE_UPGRADER_API", False):
            response = self.client.get(change_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'var owUpgradeOperationCancelUrl = "";')

    def test_firmware_image_readonly_fields_in_progress(self):
        fw = self._create_firmware_image()
        fw.extraction_status = FirmwareImage.STATUS_IN_PROGRESS
        fw.save()
        request = MockRequest()
        request.user = User.objects.first()
        fw_admin = FirmwareImageAdmin(FirmwareImage, admin.site)
        readonly = fw_admin.get_readonly_fields(request, obj=fw)
        for field in ["board", "compatible", "target", "fw_version"]:
            with self.subTest(field=field):
                self.assertIn(field, readonly)

    def test_firmware_image_readonly_fields_unconfirmed(self):
        fw = self._create_firmware_image()
        fw.extraction_status = FirmwareImage.STATUS_UNCONFIRMED
        fw.save()
        request = MockRequest()
        request.user = User.objects.first()
        fw_admin = FirmwareImageAdmin(FirmwareImage, admin.site)
        readonly = fw_admin.get_readonly_fields(request, obj=fw)
        for field in ["board", "compatible", "target", "fw_version"]:
            with self.subTest(field=field):
                self.assertIn(field, readonly)

    def test_firmware_image_readonly_fields_success_fwtool(self):
        fw = self._create_firmware_image()
        fw.extraction_status = FirmwareImage.STATUS_SUCCESS
        fw.source = "fwtool"
        fw.save()
        request = MockRequest()
        request.user = User.objects.first()
        fw_admin = FirmwareImageAdmin(FirmwareImage, admin.site)
        readonly = fw_admin.get_readonly_fields(request, obj=fw)
        for field in ["board", "compatible", "target", "fw_version"]:
            with self.subTest(field=field):
                self.assertIn(field, readonly)

    def test_firmware_image_readonly_fields_incomplete(self):
        fw = self._create_firmware_image()
        fw.extraction_status = FirmwareImage.STATUS_INCOMPLETE
        fw.source = "dtb"
        fw.save()
        request = MockRequest()
        request.user = User.objects.first()
        fw_admin = FirmwareImageAdmin(FirmwareImage, admin.site)
        readonly = fw_admin.get_readonly_fields(request, obj=fw)
        for field in ["board", "compatible"]:
            with self.subTest(field=field):
                self.assertIn(field, readonly)
        for field in ["target", "fw_version"]:
            with self.subTest(field=field):
                self.assertNotIn(field, readonly)

    def test_firmware_image_readonly_fields_failed(self):
        fw = self._create_firmware_image()
        fw.extraction_status = FirmwareImage.STATUS_FAILED
        fw.save()
        request = MockRequest()
        request.user = User.objects.first()
        fw_admin = FirmwareImageAdmin(FirmwareImage, admin.site)
        readonly = fw_admin.get_readonly_fields(request, obj=fw)
        for field in ["board", "compatible", "target", "fw_version"]:
            with self.subTest(field=field):
                self.assertNotIn(field, readonly)

    def test_firmware_image_readonly_fields_manually_confirmed(self):
        fw = self._create_firmware_image()
        fw.extraction_status = FirmwareImage.STATUS_MANUALLY_CONFIRMED
        fw.save()
        request = MockRequest()
        request.user = User.objects.first()
        fw_admin = FirmwareImageAdmin(FirmwareImage, admin.site)
        readonly = fw_admin.get_readonly_fields(request, obj=fw)
        for field in ["board", "compatible", "target", "fw_version"]:
            with self.subTest(field=field):
                self.assertIn(field, readonly)

    def test_firmware_image_readonly_fields_invalid(self):
        fw = self._create_firmware_image()
        fw.extraction_status = FirmwareImage.STATUS_INVALID
        fw.save()
        request = MockRequest()
        request.user = User.objects.first()
        fw_admin = FirmwareImageAdmin(FirmwareImage, admin.site)
        readonly = fw_admin.get_readonly_fields(request, obj=fw)
        for field in ["board", "compatible", "target", "fw_version"]:
            with self.subTest(field=field):
                self.assertIn(field, readonly)

    def test_firmware_image_compat_version_always_readonly(self):
        fw = self._create_firmware_image()
        request = MockRequest()
        request.user = User.objects.first()
        fw_admin = FirmwareImageAdmin(FirmwareImage, admin.site)
        for status in [
            FirmwareImage.STATUS_UNCONFIRMED,
            FirmwareImage.STATUS_IN_PROGRESS,
            FirmwareImage.STATUS_INCOMPLETE,
            *FirmwareImage.LOCKED_STATUSES,
            FirmwareImage.STATUS_FAILED,
            FirmwareImage.STATUS_INVALID,
        ]:
            with self.subTest(status=status):
                fw.extraction_status = status
                fw.save()
                readonly = fw_admin.get_readonly_fields(request, obj=fw)
                self.assertIn("compat_version", readonly)

    def test_firmware_image_fieldsets_hides_failure_reason_when_not_failed(self):
        fw = self._create_firmware_image()
        fw.extraction_status = FirmwareImage.STATUS_SUCCESS
        fw.save()
        request = MockRequest()
        request.user = User.objects.first()
        fw_admin = FirmwareImageAdmin(FirmwareImage, admin.site)
        fieldsets = fw_admin.get_fieldsets(request, obj=fw)
        all_fields = [f for _, opts in fieldsets for f in opts["fields"]]
        self.assertNotIn("failure_reason_display", all_fields)

    def test_firmware_image_fieldsets_shows_failure_reason_when_failed(self):
        fw = self._create_firmware_image()
        fw.extraction_status = FirmwareImage.STATUS_FAILED
        fw.failure_reason = FirmwareImage.FAILURE_UNSUPPORTED
        fw.save()
        request = MockRequest()
        request.user = User.objects.first()
        fw_admin = FirmwareImageAdmin(FirmwareImage, admin.site)
        fieldsets = fw_admin.get_fieldsets(request, obj=fw)
        all_fields = [f for _, opts in fieldsets for f in opts["fields"]]
        self.assertIn("failure_reason_display", all_fields)

    def test_firmware_image_fieldsets_shows_failure_reason_when_invalid(self):
        fw = self._create_firmware_image()
        fw.extraction_status = FirmwareImage.STATUS_INVALID
        fw.failure_reason = FirmwareImage.FAILURE_INVALID
        fw.save()
        request = MockRequest()
        request.user = User.objects.first()
        fw_admin = FirmwareImageAdmin(FirmwareImage, admin.site)
        fieldsets = fw_admin.get_fieldsets(request, obj=fw)
        all_fields = [f for _, opts in fieldsets for f in opts["fields"]]
        self.assertIn("failure_reason_display", all_fields)

    def test_firmware_image_fieldsets_exposes_compatible_for_incomplete_fwtool(self):
        fw = self._create_firmware_image()
        fw.extraction_status = FirmwareImage.STATUS_INCOMPLETE
        fw.source = "fwtool"
        fw.save()
        request = MockRequest()
        request.user = User.objects.first()
        fw_admin = FirmwareImageAdmin(FirmwareImage, admin.site)
        fieldsets = fw_admin.get_fieldsets(request, obj=fw)
        all_fields = [f for _, opts in fieldsets for f in opts["fields"]]
        self.assertIn("compatible", all_fields)
        self.assertNotIn("compatible_display", all_fields)

    def test_firmware_image_fieldsets_keeps_compatible_readonly_for_incomplete_dtb(
        self,
    ):
        fw = self._create_firmware_image()
        fw.extraction_status = FirmwareImage.STATUS_INCOMPLETE
        fw.source = "dtb"
        fw.save()
        request = MockRequest()
        request.user = User.objects.first()
        fw_admin = FirmwareImageAdmin(FirmwareImage, admin.site)
        fieldsets = fw_admin.get_fieldsets(request, obj=fw)
        all_fields = [f for _, opts in fieldsets for f in opts["fields"]]
        self.assertIn("compatible_display", all_fields)
        self.assertNotIn("compatible", all_fields)

    @mock.patch("openwisp_firmware_upgrader.tasks.extract_firmware_metadata.delay")
    def test_firmware_image_save_model_file_change_triggers_extraction(
        self, mock_delay
    ):
        fw = self._create_firmware_image()
        fw.extraction_status = FirmwareImage.STATUS_SUCCESS
        fw.board = "Old Board"
        fw.save()
        fw.file = self._get_simpleuploadedfile(self.FAKE_IMAGE_PATH2)
        request = MockRequest()
        request.user = User.objects.first()
        fw_admin = FirmwareImageAdmin(FirmwareImage, admin.site)
        form = mock.MagicMock()
        form.changed_data = ["file"]
        with self.captureOnCommitCallbacks(execute=True):
            fw_admin.save_model(request, fw, form, change=True)
        fw.refresh_from_db()
        self.assertEqual(fw.extraction_status, FirmwareImage.STATUS_UNCONFIRMED)
        self.assertEqual(fw.board, "")
        mock_delay.assert_called_once_with(str(fw.pk))

    @mock.patch("openwisp_notifications.signals.notify.send")
    @mock.patch(
        "openwisp_firmware_upgrader.base.models.AbstractCategory.metadata_extractor_class"
    )
    @mock.patch("openwisp_firmware_upgrader.tasks.extract_firmware_metadata.delay")
    def test_firmware_image_file_replacement_build_status_through_completion(
        self, mock_delay, MockExtractor, mock_notify
    ):
        MockExtractor.return_value.extract.return_value = {
            "model": "TP-Link WDR4300",
            "compatible": ["tplink,tl-wdr4300-v1"],
            "target": "ath79/generic",
            "version": "23.05.5",
            "compat_version": "1.0",
            "source": "fwtool",
            "model_confirmed": True,
        }
        fw = self._create_firmware_image()
        FirmwareImage.objects.filter(pk=fw.pk).update(
            extraction_status=FirmwareImage.STATUS_SUCCESS,
            board="Old Board",
        )
        Build.objects.filter(pk=fw.build_id).update(status=Build.BUILD_STATUS_SUCCESS)
        fw.refresh_from_db()
        fw.file = self._get_simpleuploadedfile(self.FAKE_IMAGE_PATH2)
        request = MockRequest()
        request.user = User.objects.first()
        fw_admin = FirmwareImageAdmin(FirmwareImage, admin.site)
        form = mock.MagicMock()
        form.changed_data = ["file"]
        with self.captureOnCommitCallbacks(execute=True):
            fw_admin.save_model(request, fw, form, change=True)
        mock_delay.assert_called_once_with(str(fw.pk))

        with self.subTest("build is set to analyzing immediately"):
            fw.build.refresh_from_db()
            self.assertEqual(fw.build.status, Build.BUILD_STATUS_ANALYZING)

        with self.subTest("build status and notifications are correct on completion"):
            tasks.extract_firmware_metadata.run(str(fw.pk))
            fw.refresh_from_db()
            self.assertEqual(fw.extraction_status, FirmwareImage.STATUS_SUCCESS)
            fw.build.refresh_from_db()
            self.assertEqual(fw.build.status, Build.BUILD_STATUS_SUCCESS)
            mock_notify.assert_called_once()
            self.assertEqual(mock_notify.call_args.kwargs["level"], "info")

    @mock.patch("openwisp_firmware_upgrader.admin.extract_firmware_metadata")
    def test_firmware_image_save_model_failed_to_manually_confirmed(self, mock_task):
        fw = self._create_firmware_image()
        fw.extraction_status = FirmwareImage.STATUS_FAILED
        fw.failure_reason = FirmwareImage.FAILURE_UNSUPPORTED
        fw.board = "Generic x86"
        fw.target = "x86/64"
        fw.fw_version = "23.05.5"
        fw.save()
        request = MockRequest()
        request.user = User.objects.first()
        fw_admin = FirmwareImageAdmin(FirmwareImage, admin.site)
        form = mock.MagicMock()
        form.changed_data = ["board", "target"]
        fw_admin.save_model(request, fw, form, change=True)
        fw.refresh_from_db()
        self.assertEqual(fw.extraction_status, FirmwareImage.STATUS_MANUALLY_CONFIRMED)
        self.assertEqual(fw.source, "manual")
        self.assertEqual(fw.failure_reason, "")
        mock_task.delay.assert_not_called()

    @mock.patch("openwisp_firmware_upgrader.admin.extract_firmware_metadata")
    def test_firmware_image_save_model_failed_board_required_warning(self, mock_task):
        fw = self._create_firmware_image()
        fw.extraction_status = FirmwareImage.STATUS_FAILED
        fw.board = ""
        fw.target = "x86/64"
        fw.fw_version = "23.05.5"
        fw.save()
        request = MockRequest()
        request.user = User.objects.first()
        fw_admin = FirmwareImageAdmin(FirmwareImage, admin.site)
        form = mock.MagicMock()
        form.changed_data = ["target"]
        with mock.patch.object(fw_admin, "message_user") as mock_message:
            fw_admin.save_model(request, fw, form, change=True)
        fw.refresh_from_db()
        self.assertEqual(fw.extraction_status, FirmwareImage.STATUS_FAILED)
        mock_message.assert_called_once_with(
            request,
            "Board is required to manually confirm this image.",
            30,
        )

    @mock.patch("openwisp_firmware_upgrader.admin.extract_firmware_metadata")
    def test_firmware_image_save_model_failed_compatible_only_to_manually_confirmed(
        self, mock_task
    ):
        fw = self._create_firmware_image()
        fw.extraction_status = FirmwareImage.STATUS_FAILED
        fw.failure_reason = FirmwareImage.FAILURE_UNSUPPORTED
        fw.compatible = "tplink,tl-wdr4300-v1"
        fw.save()
        request = MockRequest()
        request.user = User.objects.first()
        fw_admin = FirmwareImageAdmin(FirmwareImage, admin.site)
        form = mock.MagicMock()
        form.changed_data = ["compatible"]
        fw_admin.save_model(request, fw, form, change=True)
        fw.refresh_from_db()
        self.assertEqual(fw.extraction_status, FirmwareImage.STATUS_MANUALLY_CONFIRMED)
        self.assertEqual(fw.source, "manual")
        self.assertEqual(fw.failure_reason, "")
        mock_task.delay.assert_not_called()

    @mock.patch("openwisp_firmware_upgrader.admin.extract_firmware_metadata")
    def test_firmware_image_save_model_build_status_updated_after_manual_confirmation(
        self, mock_task
    ):
        fw = self._create_firmware_image()
        FirmwareImage.objects.filter(pk=fw.pk).update(
            extraction_status=FirmwareImage.STATUS_FAILED,
            board="Generic x86",
            target="x86/64",
        )
        Build.objects.filter(pk=fw.build_id).update(status=Build.BUILD_STATUS_FAILED)
        fw.refresh_from_db()
        request = MockRequest()
        request.user = User.objects.first()
        fw_admin = FirmwareImageAdmin(FirmwareImage, admin.site)
        form = mock.MagicMock()
        form.changed_data = ["board"]
        fw_admin.save_model(request, fw, form, change=True)
        fw.refresh_from_db()
        self.assertEqual(fw.extraction_status, FirmwareImage.STATUS_MANUALLY_CONFIRMED)
        fw.build.refresh_from_db()
        self.assertEqual(fw.build.status, Build.BUILD_STATUS_MANUALLY_CONFIRMED)
        mock_task.delay.assert_not_called()

    @mock.patch("openwisp_firmware_upgrader.admin.extract_firmware_metadata")
    def test_firmware_image_save_model_dtb_success_to_manually_confirmed(
        self, mock_task
    ):
        fw = self._create_firmware_image()
        fw.extraction_status = FirmwareImage.STATUS_INCOMPLETE
        fw.failure_reason = FirmwareImage.FAILURE_UNSUPPORTED
        fw.source = "dtb"
        fw.board = "Xunlong Orange Pi Zero"
        fw.target = ""
        fw.fw_version = ""
        fw.save()
        fw.target = "sunxi/cortexa7"
        fw.fw_version = "23.05.5"
        request = MockRequest()
        request.user = User.objects.first()
        fw_admin = FirmwareImageAdmin(FirmwareImage, admin.site)
        form = mock.MagicMock()
        form.changed_data = ["target", "fw_version"]
        fw_admin.save_model(request, fw, form, change=True)
        fw.refresh_from_db()
        self.assertEqual(fw.extraction_status, FirmwareImage.STATUS_MANUALLY_CONFIRMED)
        self.assertEqual(fw.source, "dtb")
        self.assertEqual(fw.failure_reason, "")
        mock_task.delay.assert_not_called()

    def test_firmware_image_file_replacement_blocked_after_successful_upgrade(self):
        self._login()
        fw = self._create_firmware_image()
        FirmwareImage.objects.filter(pk=fw.pk).update(
            extraction_status=FirmwareImage.STATUS_SUCCESS,
            board="TP-Link WDR4300",
            source="fwtool",
        )
        fw.refresh_from_db()
        device = self._create_config(organization=fw.build.category.organization).device
        UpgradeOperation.objects.create(device=device, image=fw, status="success")
        device_fw = DeviceFirmware(device=device, image=fw, installed=True)
        device_fw.save(upgrade=False)
        url = reverse(f"admin:{self.app_label}_firmwareimage_change", args=[fw.pk])
        data = {
            "build": str(fw.build.pk),
            "file": self._get_simpleuploadedfile(self.FAKE_IMAGE_PATH2),
            "type": fw.type,
            "_save": "Save",
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The file cannot be replaced")
        fw.refresh_from_db()
        self.assertEqual(fw.extraction_status, FirmwareImage.STATUS_SUCCESS)
        self.assertEqual(fw.board, "TP-Link WDR4300")

    def test_firmware_image_file_replacement_other_fields_not_lost(self):
        self._login()
        fw = self._create_firmware_image()
        original_build_id = fw.build_id
        FirmwareImage.objects.filter(pk=fw.pk).update(
            extraction_status=FirmwareImage.STATUS_SUCCESS,
            board="TP-Link WDR4300",
            source="fwtool",
        )
        fw.refresh_from_db()
        device = self._create_config(organization=fw.build.category.organization).device
        UpgradeOperation.objects.create(device=device, image=fw, status="success")
        device_fw = DeviceFirmware(device=device, image=fw, installed=True)
        device_fw.save(upgrade=False)
        new_build = self._create_build(category=fw.build.category, version="99.0")
        url = reverse(f"admin:{self.app_label}_firmwareimage_change", args=[fw.pk])
        data = {
            "build": str(new_build.pk),
            "file": self._get_simpleuploadedfile(self.FAKE_IMAGE_PATH2),
            "type": fw.type,
            "_save": "Save",
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The file cannot be replaced")
        fw.refresh_from_db()
        self.assertEqual(fw.build_id, original_build_id)
        self.assertEqual(fw.extraction_status, FirmwareImage.STATUS_SUCCESS)

    def test_firmware_image_file_replacement_deletes_old_file(self):
        self._login()
        fw = self._create_firmware_image()
        storage = FirmwareImage.file.field.storage
        old_file_name = fw.file.name
        self.assertTrue(storage.exists(old_file_name))
        url = reverse(f"admin:{self.app_label}_firmwareimage_change", args=[fw.pk])
        data = {
            "build": str(fw.build.pk),
            "file": self._get_simpleuploadedfile(self.FAKE_IMAGE_PATH2),
            "type": fw.type,
            "_save": "Save",
        }
        with mock.patch(
            "openwisp_firmware_upgrader.admin.extract_firmware_metadata.delay"
        ):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(url, data, follow=True)
        self.assertEqual(response.status_code, 200)
        fw.refresh_from_db()
        new_file_name = fw.file.name
        self.assertNotEqual(old_file_name, new_file_name)
        self.assertFalse(storage.exists(old_file_name))
        self.assertTrue(storage.exists(new_file_name))


class TestAdminTransaction(
    BaseTestAdmin, AdminActionPermTestMixin, TransactionTestCase
):
    _mock_upgrade = "openwisp_firmware_upgrader.upgraders.openwrt.OpenWrt.upgrade"
    _mock_connect = "openwisp_controller.connection.models.DeviceConnection.connect"

    @mock.patch(_mock_upgrade, return_value=True)
    def test_upgrade_selected_action_perms(self, *args):
        with mock.patch(self._mock_connect, return_value=True):
            env = self._create_upgrade_env()
            org = env["d1"].organization
            self._create_firmwareless_device(organization=org)
            user = self._create_user(is_staff=True)
            self._create_org_user(user=user, organization=org, is_admin=True)
            # The user is redirected to the BatchUpgradeOperation page after success operation.
            # Thus, we need to add the permission to the user.
            user.user_permissions.add(
                Permission.objects.get(
                    codename=f"change_{BatchUpgradeOperation._meta.model_name}"
                )
            )
            self._test_action_permission(
                path=self.build_list_url,
                action="upgrade_selected",
                user=user,
                obj=env["build1"],
                message=(
                    "You can track the progress of this mass upgrade operation "
                    "in this page."
                ),
                required_perms=["change"],
                extra_payload={
                    "upgrade_all": "upgrade_all",
                    "upgrade_options": '{"c": true}',
                },
            )

    @mock.patch(_mock_upgrade, return_value=True)
    def test_upgrade_related(self, *args):
        with mock.patch(self._mock_connect, return_value=True):
            self._login()
            env = self._create_upgrade_env()
            self._create_firmwareless_device(organization=env["d1"].organization)
            # check state is good before proceeding
            fw = DeviceFirmware.objects.filter(
                image__build_id=env["build2"].pk
            ).select_related("image")
            self.assertEqual(Device.objects.count(), 3)
            self.assertEqual(UpgradeOperation.objects.count(), 0)
            self.assertEqual(fw.count(), 0)

            with self.subTest("Invalid upgrade_options"):
                response = self.client.post(
                    self.build_list_url,
                    {
                        "action": "upgrade_selected",
                        "upgrade_related": "upgrade_related",
                        "upgrade_options": "invalid",
                        ACTION_CHECKBOX_NAME: (env["build2"].pk,),
                    },
                    follow=True,
                )
                id_attr = (
                    ' id="id_upgrade_options_error"' if django.VERSION >= (5, 2) else ""
                )
                self.assertContains(
                    response,
                    f'<ul class="errorlist"{id_attr}><li>Enter a valid JSON.</li></ul>',
                )

            with self.subTest("Test with valid upgrade_options"):
                r = self.client.post(
                    self.build_list_url,
                    {
                        "action": "upgrade_selected",
                        "upgrade_related": "upgrade_related",
                        "upgrade_options": '{"c": true}',
                        ACTION_CHECKBOX_NAME: (env["build2"].pk,),
                    },
                    follow=True,
                )
                self.assertContains(r, '<li class="success">')
                self.assertContains(r, "track the progress")
                self.assertEqual(
                    UpgradeOperation.objects.filter(
                        upgrade_options={"c": True}
                    ).count(),
                    2,
                )
                self.assertEqual(fw.count(), 2)

    @mock.patch(_mock_upgrade, return_value=True)
    def test_upgrade_all(self, *args):
        with mock.patch(self._mock_connect, return_value=True):
            self._login()
            env = self._create_upgrade_env()
            self._create_firmwareless_device(organization=env["d1"].organization)
            # check state is good before proceeding
            fw = DeviceFirmware.objects.filter(
                image__build_id=env["build2"].pk
            ).select_related("image")
            self.assertEqual(Device.objects.count(), 3)
            self.assertEqual(UpgradeOperation.objects.count(), 0)
            self.assertEqual(fw.count(), 0)

            with self.subTest("Invalid upgrade_options"):
                response = self.client.post(
                    self.build_list_url,
                    {
                        "action": "upgrade_selected",
                        "upgrade_all": "upgrade_all",
                        "upgrade_options": "invalid",
                        ACTION_CHECKBOX_NAME: (env["build2"].pk,),
                    },
                    follow=True,
                )
                self.assertEqual(response.status_code, 200)
                id_attr = (
                    ' id="id_upgrade_options_error"' if django.VERSION >= (5, 2) else ""
                )
                self.assertContains(
                    response,
                    f'<ul class="errorlist"{id_attr}><li>Enter a valid JSON.</li></ul>',
                )

            with self.subTest("Test with valid upgrade_options"):
                response = self.client.post(
                    self.build_list_url,
                    {
                        "action": "upgrade_selected",
                        "upgrade_all": "upgrade_all",
                        "upgrade_options": '{"c": true}',
                        ACTION_CHECKBOX_NAME: (env["build2"].pk,),
                    },
                    follow=True,
                )
                self.assertContains(response, '<li class="success">')
                self.assertContains(response, "track the progress")
                self.assertEqual(
                    UpgradeOperation.objects.filter(
                        upgrade_options={"c": True}
                    ).count(),
                    3,
                )
                self.assertEqual(fw.count(), 3)
                self.assertContains(
                    response,
                    (
                        '<div class="readonly"><ul class="readonly-upgrade-options">'
                        '<li><img src="/static/admin/img/icon-yes.svg" alt="yes">'
                        "Attempt to preserve all changed files in /etc/ (-c)</li>"
                        '<li><img src="/static/admin/img/icon-no.svg" alt="no">'
                        "Attempt to preserve all changed files in /, except those from "
                        "packages but including changed confs. (-o)</li>"
                        '<li><img src="/static/admin/img/icon-no.svg" alt="no">'
                        "Do not save configuration over reflash (-n)</li>"
                        '<li><img src="/static/admin/img/icon-no.svg" alt="no">'
                        "Skip from backup files that are equal to those in /rom (-u)</li>"
                        '<li><img src="/static/admin/img/icon-no.svg" alt="no">'
                        "Do not attempt to restore the partition table after flash. (-p)</li>"
                        '<li><img src="/static/admin/img/icon-no.svg" alt="no">'
                        "Include in backup a list of current installed packages at "
                        "/etc/backup/installed_packages.txt (-k)</li>"
                        '<li><img src="/static/admin/img/icon-no.svg" alt="no">'
                        "Flash image even if image checks fail, this is dangerous! (-F)</li></ul></div>"
                    ),
                    html=True,
                )

    @mock.patch(_mock_upgrade, return_value=True)
    def test_mass_upgrade_shared_image(self, *args):
        with mock.patch(self._mock_connect, return_value=True):
            self._login()
            shared_image = self._create_firmware_image(organization=None)
            shared_build = shared_image.build
            self._create_device_with_connection(
                organization=self._create_org(name="org1"),
                model=shared_image.boards[0],
            )
            self._create_device_with_connection(
                organization=self._create_org(name="org2"),
                model=shared_image.boards[0],
            )
            fw = DeviceFirmware.objects.filter(
                image__build_id=shared_build.pk
            ).select_related("image")
            self.assertEqual(Device.objects.count(), 2)
            self.assertEqual(UpgradeOperation.objects.count(), 0)
            self.assertEqual(fw.count(), 0)

            response = self.client.post(
                self.build_list_url,
                {
                    "action": "upgrade_selected",
                    "upgrade_all": "upgrade_all",
                    "upgrade_options": '{"c": true}',
                    ACTION_CHECKBOX_NAME: (shared_build.pk,),
                },
                follow=True,
            )
            self.assertContains(response, '<li class="success">')
            self.assertContains(response, "track the progress")
            self.assertEqual(
                UpgradeOperation.objects.filter(upgrade_options={"c": True}).count(), 2
            )
            self.assertEqual(fw.count(), 2)

    @mock.patch(_mock_upgrade, return_value=True)
    def test_massive_upgrade_operation_page(self, *args):
        with mock.patch(self._mock_connect, return_value=True):
            self.test_upgrade_all()
            uo = UpgradeOperation.objects.first()
            url = reverse(
                f"admin:{self.app_label}_batchupgradeoperation_change",
                args=[uo.batch.pk],
            )
            response = self.client.get(url)
            self.assertContains(response, "Success rate")
            self.assertContains(response, "Failure rate")
            self.assertContains(response, "Abortion rate")

    @mock.patch(_mock_upgrade, return_value=True)
    def test_upgrade_operation_change_breadcrumb_with_batch(self, *args):
        with mock.patch(self._mock_connect, return_value=True):
            self.test_upgrade_all()
            uo = UpgradeOperation.objects.first()
            url = reverse(
                f"admin:{self.app_label}_upgradeoperation_change", args=[uo.pk]
            )
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            batch_changelist_url = reverse(
                f"admin:{self.app_label}_batchupgradeoperation_changelist"
            )
            batch_change_url = reverse(
                f"admin:{self.app_label}_batchupgradeoperation_change",
                args=[uo.batch.pk],
            )
            self.assertTrue(response.context["batch_has_view_permission"])
            self.assertEqual(response.context["batch"], uo.batch)
            self.assertContains(response, batch_changelist_url)
            self.assertContains(response, batch_change_url)
            self.assertContains(response, str(uo.batch))
            generic_upgrade_changelist_url = reverse(
                f"admin:{self.app_label}_upgradeoperation_changelist"
            )
            self.assertNotContains(response, f'href="{generic_upgrade_changelist_url}"')

    @mock.patch(_mock_upgrade, return_value=True)
    def test_upgrade_operation_change_breadcrumb_without_batch(self, *args):
        with mock.patch(self._mock_connect, return_value=True):
            self._login()
            device_fw = self._create_device_firmware()
            device_fw.save(upgrade=True)
            uo = device_fw.device.upgradeoperation_set.first()
            self.assertIsNone(uo.batch_id)
            url = reverse(
                f"admin:{self.app_label}_upgradeoperation_change", args=[uo.pk]
            )
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(response.context.get("batch"))
            generic_upgrade_changelist_url = reverse(
                f"admin:{self.app_label}_upgradeoperation_changelist"
            )
            self.assertContains(response, f'href="{generic_upgrade_changelist_url}"')

    @mock.patch(_mock_upgrade, return_value=True)
    def test_upgrade_operation_change_breadcrumb_with_batch_no_permission(self, *args):
        with mock.patch(self._mock_connect, return_value=True):
            self.test_upgrade_all()
            uo = UpgradeOperation.objects.first()
            url = reverse(
                f"admin:{self.app_label}_upgradeoperation_change", args=[uo.pk]
            )
            with mock.patch(
                "openwisp_firmware_upgrader.admin.BatchUpgradeOperationAdmin.has_view_permission",
                return_value=False,
            ):
                response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            batch_changelist_url = reverse(
                f"admin:{self.app_label}_batchupgradeoperation_changelist"
            )
            batch_change_url = reverse(
                f"admin:{self.app_label}_batchupgradeoperation_change",
                args=[uo.batch.pk],
            )
            self.assertFalse(response.context["batch_has_view_permission"])
            self.assertEqual(response.context["batch"], uo.batch)
            breadcrumbs = (
                response.content.decode()
                .split('<div class="breadcrumbs">', 1)[1]
                .split("</div>", 1)[0]
            )
            self.assertNotIn(f'href="{batch_changelist_url}"', breadcrumbs)
            self.assertNotIn(f'href="{batch_change_url}"', breadcrumbs)
            generic_upgrade_changelist_url = reverse(
                f"admin:{self.app_label}_upgradeoperation_changelist"
            )
            self.assertNotIn(f'href="{generic_upgrade_changelist_url}"', breadcrumbs)
            self.assertIn(str(uo.batch), breadcrumbs)

    @mock.patch(_mock_upgrade, return_value=True)
    def test_recent_upgrades(self, *args):
        with mock.patch(self._mock_connect, return_value=True):
            self._login()
            env = self._create_upgrade_env()
            url = reverse(
                f"admin:{self.config_app_label}_device_change", args=[env["d2"].pk]
            )
            r = self.client.get(url)
            self.assertNotContains(r, "Recent Firmware Upgrades")
            env["build2"].batch_upgrade(firmwareless=True)
            r = self.client.get(url)
            self.assertContains(r, "Recent Firmware Upgrades")

    @mock.patch(_mock_upgrade, return_value=True)
    def test_upgrade_operation_inline(self, *args):
        with mock.patch(self._mock_connect, return_value=True):
            device_fw = self._create_device_firmware()
            device_fw.save(upgrade=True)
            device = device_fw.device
            request = self.make_device_admin_request(device.pk)
            request.user = User.objects.first()
            deviceadmin = DeviceAdmin(model=Device, admin_site=admin.site)
            self.assertNotIn(
                DeviceUpgradeOperationInline, deviceadmin.get_inlines(request, obj=None)
            )
            self.assertIn(
                DeviceUpgradeOperationInline,
                deviceadmin.get_inlines(request, obj=device),
            )

    @mock.patch(_mock_upgrade, return_value=True)
    def test_upgrade_operation_inline_queryset(self, *args):
        with mock.patch(self._mock_connect, return_value=True):
            device_fw = self._create_device_firmware()
            device_fw.save(upgrade=True)
            # expect only 1
            uo = device_fw.device.upgradeoperation_set.get()
            device = device_fw.device
            request = self.make_device_admin_request(device.pk)
            request.user = User.objects.first()
            inline = DeviceUpgradeOperationInline(Device, admin.site)
            qs = inline.get_queryset(request)
            self.assertEqual(qs.count(), 1)
            self.assertIn(uo, qs)
            uo.created = localtime() - timedelta(days=30)
            uo.modified = uo.created
            uo.save()
            qs = inline.get_queryset(request)
            self.assertEqual(qs.count(), 0)

    @mock.patch(_mock_upgrade, return_value=True)
    def test_device_firmware_upgrade_options(self, *args):
        with mock.patch(self._mock_connect, return_value=True):
            self._login()
            device_fw = self._create_device_firmware()
            device = device_fw.device
            device_conn = device.deviceconnection_set.first()
            build = self._create_build(version="0.2")
            image = self._create_firmware_image(build=build)
            upgrade_options = {
                "c": True,
                "o": False,
                "u": False,
                "n": False,
                "p": False,
                "k": False,
                "F": True,
            }
            device_params = self._get_device_params(
                device, device_conn, image, device_fw, json.dumps(upgrade_options)
            )
            response = self.client.post(
                reverse(
                    f"admin:{self.config_app_label}_device_change", args=[device.id]
                ),
                data=device_params,
                follow=True,
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(device.upgradeoperation_set.count(), 1)
            upgrade_operation = device.upgradeoperation_set.first()
            self.assertEqual(upgrade_operation.upgrade_options, upgrade_options)
            self.assertContains(
                response,
                (
                    '<div class="readonly"><ul class="readonly-upgrade-options"><li>'
                    '<img src="/static/admin/img/icon-yes.svg" alt="yes">'
                    "Attempt to preserve all changed files in /etc/ (-c)</li>"
                    '<li><img src="/static/admin/img/icon-no.svg" alt="no">'
                    "Attempt to preserve all changed files in /, except those from packages "
                    "but including changed confs. (-o)</li>"
                    '<li><img src="/static/admin/img/icon-no.svg" '
                    'alt="no">Do not save configuration over reflash (-n)</li>'
                    '<li><img src="/static/admin/img/icon-no.svg" alt="no">Skip from backup files '
                    "that are equal to those in /rom (-u)</li>"
                    '<li><img src="/static/admin/img/icon-no.svg" alt="no">'
                    "Do not attempt to restore the partition table after flash. (-p)</li>"
                    '<li><img src="/static/admin/img/icon-no.svg" alt="no">'
                    "Include in backup a list of current installed packages at "
                    "/etc/backup/installed_packages.txt (-k)</li>"
                    '<li><img src="/static/admin/img/icon-yes.svg" alt="yes">'
                    "Flash image even if image checks fail, this is dangerous! (-F)</li></ul></div>"
                ),
                html=True,
            )

    @mock.patch(_mock_upgrade, return_value=True)
    @mock.patch.object(OpenWisp1, "SCHEMA", None)
    def test_using_upgrade_options_with_unsupported_upgrader(self, *args):
        with mock.patch(self._mock_connect, return_value=True):
            self._login()
            device_fw = self._create_device_firmware()
            device = device_fw.device
            device.config.backend = "netjsonconfig.OpenWisp"
            device.config.save()
            device_conn = device.deviceconnection_set.first()
            device_conn.update_strategy = conn_settings.DEFAULT_UPDATE_STRATEGIES[1][0]
            device_conn.save()
            build = self._create_build(version="0.2")
            image = self._create_firmware_image(build=build)
            upgrade_options = {
                "c": True,
                "o": False,
                "u": False,
                "n": False,
                "p": False,
                "k": False,
                "F": True,
            }

            device_params = self._get_device_params(
                device, device_conn, image, device_fw, json.dumps(upgrade_options)
            )
            device_params.update(
                {
                    "model": device.model,
                    "devicefirmware-0-image": str(image.id),
                    "devicefirmware-0-id": str(device_fw.id),
                    "devicefirmware-0-upgrade_options": json.dumps(upgrade_options),
                    "organization": str(device.organization.id),
                    "config-0-id": str(device.config.pk),
                    "config-0-device": str(device.id),
                    "deviceconnection_set-0-credentials": str(
                        device_conn.credentials_id
                    ),
                    "deviceconnection_set-0-id": str(device_conn.id),
                    "deviceconnection_set-0-update_strategy": (
                        conn_settings.DEFAULT_UPDATE_STRATEGIES[1][0]
                    ),
                    "deviceconnection_set-0-enabled": True,
                    "devicefirmware-TOTAL_FORMS": 1,
                    "devicefirmware-INITIAL_FORMS": 1,
                    "upgradeoperation_set-TOTAL_FORMS": 0,
                    "upgradeoperation_set-INITIAL_FORMS": 0,
                    "upgradeoperation_set-MIN_NUM_FORMS": 0,
                    "upgradeoperation_set-MAX_NUM_FORMS": 0,
                    "_continue": True,
                }
            )

            with self.subTest("Test DeviceFirmwareInline does not have schema defined"):
                response = self.client.get(
                    reverse(
                        f"admin:{self.config_app_label}_device_change", args=[device.id]
                    )
                )
                self.assertContains(
                    response, "<script>\nvar firmwareUpgraderSchema = null\n"
                )

            with self.subTest("Test using upgrade options with unsupported upgrader"):
                response = self.client.post(
                    reverse(
                        f"admin:{self.config_app_label}_device_change", args=[device.id]
                    ),
                    data=device_params,
                    follow=True,
                )
                self.assertContains(
                    response,
                    (
                        '<ul class="errorlist nonfield"><li>Using upgrade '
                        "options is not allowed with this upgrader.</li></ul>"
                    ),
                )

            with self.subTest("Test upgrading without upgrade options"):
                del device_params["devicefirmware-0-upgrade_options"]
                response = self.client.post(
                    reverse(
                        f"admin:{self.config_app_label}_device_change", args=[device.id]
                    ),
                    data=device_params,
                    follow=True,
                )
                self.assertContains(
                    response,
                    (
                        '<div class="readonly">Upgrade options are '
                        "not supported for this upgrader.</div>"
                    ),
                )

    @mock.patch(_mock_upgrade, return_value=True)
    def test_batch_upgrade_operation_status_filter(self, *args):
        """Test status filtering in batch upgrade operation admin page"""
        with mock.patch(self._mock_connect, return_value=True):
            self._login()
            env = self._create_upgrade_env()
            env["category"].organization = None
            env["category"].save()
            batch = env["build2"].batch_upgrade(firmwareless=True)
            # Create upgrade operations with different statuses
            upgrade_ops = list(batch.upgradeoperation_set.all())
            if len(upgrade_ops) >= 2:
                upgrade_ops[0].status = "success"
                upgrade_ops[0].save()
                upgrade_ops[1].status = "failed"
                upgrade_ops[1].save()
            url = reverse(
                f"admin:{self.app_label}_batchupgradeoperation_change", args=[batch.pk]
            )

            with self.subTest("Test no filter - shows all operations"):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "ow-filter status")
                self.assertContains(response, "By status")
                self.assertContains(response, "By organization")

            with self.subTest("Test status success filter"):
                response = self.client.get(url + "?status=success")
                self.assertEqual(response.status_code, 200)
                success_ops = batch.upgradeoperation_set.filter(status="success")
                for op in success_ops:
                    self.assertContains(response, op.device.name)

            with self.subTest("Test status failed filter"):
                response = self.client.get(url + "?status=failed")
                self.assertEqual(response.status_code, 200)
                failed_ops = batch.upgradeoperation_set.filter(status="failed")
                for op in failed_ops:
                    self.assertContains(response, op.device.name)

            with self.subTest("Test status idle filter"):
                response = self.client.get(url + "?status=idle")
                self.assertEqual(response.status_code, 200)
                idle_ops = batch.upgradeoperation_set.filter(status="idle")
                for op in idle_ops:
                    self.assertContains(response, op.device.name)

    @mock.patch(_mock_upgrade, return_value=True)
    def test_batch_upgrade_operation_organization_filter(self, *args):
        """Test organization filtering in batch upgrade operation admin page"""
        with mock.patch(self._mock_connect, return_value=True):
            self._login()
            # Create devices from different organizations
            org1 = self._create_org(name="Org1", slug="org1")
            org2 = self._create_org(name="Org2", slug="org2")
            device1 = self._create_device(organization=org1, name="device1-org-filter")
            device2 = self._create_device(organization=org2, name="device2-org-filter")
            self._create_config(device=device1)
            self._create_config(device=device2)
            cred1 = self._get_credentials(organization=org1)
            cred2 = self._get_credentials(organization=org2)
            self._create_device_connection(device=device1, credentials=cred1)
            self._create_device_connection(device=device2, credentials=cred2)
            shared_category = self._create_category(
                organization=None, name="Shared Category"
            )
            build = self._create_build(category=shared_category)
            image = self._create_firmware_image(build=build)
            self._create_device_firmware(
                device=device1, image=image, device_connection=False
            )
            self._create_device_firmware(
                device=device2, image=image, device_connection=False
            )
            batch = build.batch_upgrade(firmwareless=False)
            url = reverse(
                f"admin:{self.app_label}_batchupgradeoperation_change", args=[batch.pk]
            )

            with self.subTest("Test no organization filter - shows all operations"):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, device1.name)
                self.assertContains(response, device2.name)
                self.assertContains(response, "By organization")

            with self.subTest("Test organization filter for org1"):
                response = self.client.get(url + f"?organization={org1.id}")
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, device1.name)
                self.assertNotContains(response, device2.name)

            with self.subTest("Test organization filter for org2"):
                response = self.client.get(url + f"?organization={org2.id}")
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, device1.name)
                self.assertContains(response, device2.name)

    @mock.patch(_mock_upgrade, return_value=True)
    def test_batch_upgrade_operation_combined_filters(self, *args):
        """Test combining status and organization filters"""
        with mock.patch(self._mock_connect, return_value=True):
            self._login()
            # Create devices from different organizations
            org1 = self._create_org(name="Org1", slug="org1")
            org2 = self._create_org(name="Org2", slug="org2")
            device1 = self._create_device(
                organization=org1, name="device1-combined-filter"
            )
            device2 = self._create_device(
                organization=org2, name="device2-combined-filter"
            )
            self._create_config(device=device1)
            self._create_config(device=device2)
            cred1 = self._get_credentials(organization=org1)
            cred2 = self._get_credentials(organization=org2)
            self._create_device_connection(device=device1, credentials=cred1)
            self._create_device_connection(device=device2, credentials=cred2)

            # Create shared build and batch upgrade that works with any organization
            shared_category = self._create_category(
                organization=None, name="Shared Category"
            )
            build = self._create_build(category=shared_category)
            image = self._create_firmware_image(build=build)
            self._create_device_firmware(
                device=device1, image=image, device_connection=False
            )
            self._create_device_firmware(
                device=device2, image=image, device_connection=False
            )
            batch = build.batch_upgrade(firmwareless=False)
            # Set different statuses for devices from different orgs
            upgrade_ops = list(batch.upgradeoperation_set.all())
            org1_op = (
                upgrade_ops[0]
                if upgrade_ops[0].device.organization == org1
                else upgrade_ops[1]
            )
            org2_op = (
                upgrade_ops[1]
                if upgrade_ops[1].device.organization == org2
                else upgrade_ops[0]
            )
            org1_op.status = "success"
            org1_op.save()
            org2_op.status = "failed"
            org2_op.save()
            url = reverse(
                f"admin:{self.app_label}_batchupgradeoperation_change", args=[batch.pk]
            )

            with self.subTest("Test combined filter: org1 + success"):
                response = self.client.get(
                    url + f"?organization={org1.id}&status=success"
                )
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, org1_op.device.name)
                self.assertNotContains(response, org2_op.device.name)

            with self.subTest("Test combined filter: org2 + failed"):
                response = self.client.get(
                    url + f"?organization={org2.id}&status=failed"
                )
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, org1_op.device.name)
                self.assertContains(response, org2_op.device.name)

            with self.subTest("Test combined filter: org1 + failed (no results)"):
                response = self.client.get(
                    url + f"?organization={org1.id}&status=failed"
                )
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, org1_op.device.name)
                self.assertNotContains(response, org2_op.device.name)

            with self.subTest(
                "Combined filters preserve each other in generated links"
            ):
                response = self.client.get(
                    url + f"?organization={org1.id}&status=success"
                )
                # Organization 'All' should keep status
                self.assertContains(
                    response,
                    '<a title="All" href="?status=success">All</a>',
                    html=True,
                )
                # Status 'All' should keep organization
                self.assertContains(
                    response,
                    f'<a title="All" href="?organization={org1.id}">All</a>',
                    html=True,
                )

    @mock.patch(_mock_upgrade, return_value=True)
    def test_batch_upgrade_operation_filter_search_combination(self, *args):
        """Test combining search with filters"""
        with mock.patch(self._mock_connect, return_value=True):
            self._login()
            env = self._create_upgrade_env()
            batch = env["build2"].batch_upgrade(firmwareless=True)

            upgrade_op = batch.upgradeoperation_set.first()
            upgrade_op.device.name = "unique-test-device"
            upgrade_op.device.save()
            upgrade_op.status = "success"
            upgrade_op.save()

            url = reverse(
                f"admin:{self.app_label}_batchupgradeoperation_change", args=[batch.pk]
            )
            with self.subTest("Test search + status filter"):
                with self.assertNumQueries(25 if django.VERSION < (5, 2) else 23):
                    response = self.client.get(url + "?q=unique-test&status=success")
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "unique-test-device")
                self.assertContains(
                    response,
                    '<a title="All" href="?q=unique-test">All</a>',
                    html=True,
                )

            with self.subTest("Test search + status filter (no match)"):
                response = self.client.get(url + "?q=unique-test&status=failed")
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, "unique-test-device")

    @mock.patch(_mock_upgrade, return_value=True)
    def test_batch_upgrade_confirmation_form_multitenancy(self, *args):
        """Test BatchUpgradeConfirmationForm multitenancy for organization admin vs superuser."""
        with mock.patch(self._mock_connect, return_value=True):
            # Setup common objects
            org1 = self._get_org()
            org2 = self._create_org(name="Org 2", slug="org2")
            group1 = self._create_device_group(name="Group Org1", organization=org1)
            group2 = self._create_device_group(name="Group Org2", organization=org2)
            location1 = Location.objects.create(
                name="Location Org1", address="123 Test St", organization=org1
            )
            location2 = Location.objects.create(
                name="Location Org2", address="456 Test St", organization=org2
            )
            category_org1 = self._create_category(organization=org1)
            build_org1 = self._create_build(category=category_org1)
            category_shared = self._create_category(organization=None)
            build_shared = self._create_build(category=category_shared)
            category_org2 = self._create_category(organization=org2)
            build_org2 = self._create_build(category=category_org2)
            superuser = self._get_admin()
            org_admin = self._create_administrator(organizations=[org1])

            with self.subTest("Superuser: Org build should shown related org objects"):
                form = BatchUpgradeConfirmationForm(
                    initial={"build": build_org1}, user=superuser
                )
                self.assertIn(group1, form.fields["group"].queryset)
                self.assertNotIn(group2, form.fields["group"].queryset)
                self.assertIn(location1, form.fields["location"].queryset)
                self.assertNotIn(location2, form.fields["location"].queryset)

            with self.subTest("Superuser: Shared build should show all org objects"):
                form = BatchUpgradeConfirmationForm(
                    initial={"build": build_shared}, user=superuser
                )
                self.assertIn(group1, form.fields["group"].queryset)
                self.assertIn(group2, form.fields["group"].queryset)
                self.assertIn(location1, form.fields["location"].queryset)
                self.assertIn(location2, form.fields["location"].queryset)

            with self.subTest(
                "Org admin: Shared build should show only managed org objects"
            ):
                form = BatchUpgradeConfirmationForm(
                    initial={"build": build_shared}, user=org_admin
                )
                self.assertIn(group1, form.fields["group"].queryset)
                self.assertNotIn(group2, form.fields["group"].queryset)
                self.assertIn(location1, form.fields["location"].queryset)
                self.assertNotIn(location2, form.fields["location"].queryset)

            with self.subTest("Org admin: Org build should show only that org objects"):
                form = BatchUpgradeConfirmationForm(
                    initial={"build": build_org1}, user=org_admin
                )
                self.assertIn(group1, form.fields["group"].queryset)
                self.assertNotIn(group2, form.fields["group"].queryset)
                self.assertIn(location1, form.fields["location"].queryset)
                self.assertNotIn(location2, form.fields["location"].queryset)

            with self.subTest("Org admin: Different org build should show no objects"):
                form = BatchUpgradeConfirmationForm(
                    initial={"build": build_org2}, user=org_admin
                )
                self.assertEqual(form.fields["group"].queryset.count(), 0)
                self.assertEqual(form.fields["location"].queryset.count(), 0)

            with self.subTest("Location field exists and is not required"):
                form = BatchUpgradeConfirmationForm(
                    initial={"build": build_org1}, user=superuser
                )
                self.assertIn("location", form.fields)
                self.assertFalse(form.fields["location"].required)
                self.assertIn("location", form.fields["location"].help_text)

    @mock.patch(_mock_upgrade, return_value=True)
    def test_batch_upgrade_with_location_admin_action(self, *args):
        """Test mass upgrade admin action with location filtering."""
        with mock.patch(self._mock_connect, return_value=True):
            self._login()
            org = self._get_org()
            category = self._create_category(organization=org)
            build = self._create_build(category=category)
            image = self._create_firmware_image(build=build)
            # Create location
            location = Location.objects.create(
                name="Test Location", address="123 Test St", organization=org
            )
            # Create devices
            device1 = self._create_device(
                name="Device1-WithLocation",
                organization=org,
                model=image.boards[0],
                mac_address="00:11:22:33:55:71",
            )
            device2 = self._create_device(
                name="Device2-NoLocation",
                organization=org,
                model=image.boards[0],
                mac_address="00:11:22:33:55:72",
            )
            # Set location for device1 only
            DeviceLocation.objects.create(content_object=device1, location=location)
            # Create configs and connections
            self._create_config(device=device1)
            self._create_config(device=device2)
            cred1 = self._get_credentials(organization=org)
            if not DeviceConnection.objects.filter(
                device=device1, credentials=cred1
            ).exists():
                self._create_device_connection(device=device1, credentials=cred1)
            if not DeviceConnection.objects.filter(
                device=device2, credentials=cred1
            ).exists():
                self._create_device_connection(device=device2, credentials=cred1)
            url = reverse(f"admin:{self.app_label}_build_changelist")
            data = {
                ACTION_CHECKBOX_NAME: [build.pk],
                "action": "upgrade_selected",
                "location": location.pk,
                "upgrade_related": "on",
            }
            with self.subTest("Test upgrade confirmation page with location"):
                response = self.client.post(url, data, follow=True)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, location.name)
            # Submit the actual upgrade with location filter
            data.update(
                {
                    "upgrade_all": "on",
                    "location": location.pk,
                }
            )
            with self.subTest("Test actual batch upgrade with location"):
                with mock.patch(
                    "openwisp_firmware_upgrader.tasks.upgrade_firmware.delay"
                ):
                    response = self.client.post(url, data, follow=True)
                    self.assertEqual(response.status_code, 200)
                # Check that batch was created with location
                batch = BatchUpgradeOperation.objects.first()
                self.assertIsNotNone(batch)
                self.assertEqual(batch.location, location)

    @mock.patch(_mock_upgrade, return_value=True)
    def test_batch_upgrade_operation_admin_location_field(self, *args):
        """Test location field in BatchUpgradeOperationAdmin."""
        with mock.patch(self._mock_connect, return_value=True):
            self._login()
            org = self._get_org()
            category = self._create_category(organization=org)
            build = self._create_build(category=category)
            location = Location.objects.create(
                name="Test Location", address="123 Test St", organization=org
            )
            batch = BatchUpgradeOperation.objects.create(build=build, location=location)
            url = reverse(
                f"admin:{self.app_label}_batchupgradeoperation_change", args=[batch.pk]
            )
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, location.name)

    @mock.patch(_mock_upgrade, return_value=True)
    def test_batch_upgrade_no_devices_error_handling(self, *args):
        """Test admin error handling when filters don't match any devices."""
        with mock.patch(self._mock_connect, return_value=True):
            self._login()
            org = self._get_org()
            category = self._create_category(organization=org)
            build = self._create_build(category=category, version="error-test")
            # Create location and group but no devices matching both
            location = Location.objects.create(
                name="Empty Location", address="456 Empty St", organization=org
            )
            group = self._create_device_group(name="Empty Group", organization=org)
            url = reverse(f"admin:{self.app_label}_build_changelist")
            data = {
                ACTION_CHECKBOX_NAME: [build.pk],
                "action": "upgrade_selected",
                "location": location.pk,
                "group": group.pk,
                "upgrade_all": "on",
            }
            with self.subTest("Test error message when no devices match filters"):
                response = self.client.post(url, data, follow=True)
                self.assertEqual(response.status_code, 200)
                # Should stay on confirmation page with error message
                self.assertContains(response, "No devices found matching")
                self.assertContains(
                    response, "adjust your group and/or location filters"
                )
                # No batch should be created
                self.assertEqual(BatchUpgradeOperation.objects.count(), 0)

    @mock.patch(_mock_upgrade, return_value=True)
    def test_batch_upgrade_operation_list_location_filter(self, *args):
        """Test location filter in BatchUpgradeOperation list view."""
        with mock.patch(self._mock_connect, return_value=True):
            self._login()
            org = self._get_org()
            category = self._create_category(
                name="Location Filter Test Category", organization=org
            )
            build = self._create_build(category=category, version="location-test-1.0")
            location1 = Location.objects.create(
                name="Location 1", address="123 Main St", organization=org
            )
            location2 = Location.objects.create(
                name="Location 2", address="456 Oak Ave", organization=org
            )
            # Create batch operations with different locations
            batch1 = BatchUpgradeOperation.objects.create(
                build=build, location=location1
            )
            batch2 = BatchUpgradeOperation.objects.create(
                build=build, location=location2
            )
            batch3 = BatchUpgradeOperation.objects.create(
                build=build, location=None  # No location
            )
            url = reverse(f"admin:{self.app_label}_batchupgradeoperation_changelist")
            with self.subTest("Test no location filter - shows all batches"):
                with self.assertNumQueries(5):
                    response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, str(batch1.pk))
                self.assertContains(response, str(batch2.pk))
                self.assertContains(response, str(batch3.pk))

            with self.subTest("Test location1 filter"):
                with self.assertNumQueries(4):
                    response = self.client.get(url + f"?location={location1.pk}")
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, str(batch1.pk))
                self.assertNotContains(response, str(batch2.pk))
                self.assertNotContains(response, str(batch3.pk))

    @mock.patch(
        "openwisp_controller.connection.apps.ConnectionConfig._launch_update_config"
    )
    def test_device_firmware_inline_deactivated_device(self, *args):
        self._login()
        device_fw = self._create_device_firmware()
        device = device_fw.device
        device_conn = device.deviceconnection_set.first()
        device.deactivate()
        # Record initial state before attempting to modify deactivated device
        initial_device_fw_count = DeviceFirmware.objects.filter(device=device).count()
        initial_upgrade_op_count = UpgradeOperation.objects.filter(
            device=device
        ).count()
        initial_total_device_fw_count = DeviceFirmware.objects.count()
        initial_total_upgrade_op_count = UpgradeOperation.objects.count()
        # Try to add a new DeviceFirmware via admin interface
        device_params = self._get_device_params(device, device_conn, device_fw.image)
        device_params.update(
            {
                "devicefirmware-0-image": str(device_fw.image.id),
                "devicefirmware-TOTAL_FORMS": 1,
                "devicefirmware-INITIAL_FORMS": 0,
            }
        )
        response = self.client.post(
            reverse(f"admin:{self.config_app_label}_device_change", args=[device.id]),
            data=device_params,
            follow=True,
        )
        self.assertEqual(response.status_code, 403)
        # Verify no database side effects occurred
        self.assertEqual(
            DeviceFirmware.objects.filter(device=device).count(),
            initial_device_fw_count,
            "DeviceFirmware count for deactivated device should remain unchanged",
        )
        self.assertEqual(
            UpgradeOperation.objects.filter(device=device).count(),
            initial_upgrade_op_count,
            "UpgradeOperation count for deactivated device should remain unchanged",
        )
        self.assertEqual(
            DeviceFirmware.objects.count(),
            initial_total_device_fw_count,
            "Total DeviceFirmware count should remain unchanged",
        )
        self.assertEqual(
            UpgradeOperation.objects.count(),
            initial_total_upgrade_op_count,
            "Total UpgradeOperation count should remain unchanged",
        )


class TestUpgradeOperationInlineDeletePermission(BaseTestAdmin, TestCase):
    def test_cascade_delete_integration(self):
        self._login()
        org = self._create_org(name="cascade-org", slug="cascade-org")
        category = self._create_category(name="Cascade Category", organization=org)
        build = self._create_build(category=category, version="9.9")
        batch = BatchUpgradeOperation.objects.create(build=build)
        device = self._create_device_with_connection(organization=org)
        device.deactivate()
        device.config.set_status_deactivated()
        operation = UpgradeOperation.objects.create(
            device=device, batch=batch, status="success"
        )
        delete_url = reverse(
            f"admin:{Organization._meta.app_label}"
            f"_{Organization._meta.model_name}_delete",
            args=[org.pk],
        )
        response = self.client.post(delete_url, data={"post": "yes"}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Organization.objects.filter(pk=org.pk).exists())
        self.assertFalse(BatchUpgradeOperation.objects.filter(pk=batch.pk).exists())
        self.assertFalse(UpgradeOperation.objects.filter(pk=operation.pk).exists())

    def test_cascade_delete_with_in_progress_operation(self):
        self._login()
        org = self._create_org(
            name="in-progress-cascade-org", slug="in-progress-cascade-org"
        )
        category = self._create_category(name="Cascade Category", organization=org)
        build = self._create_build(category=category, version="9.9")
        batch = BatchUpgradeOperation.objects.create(build=build, status="success")
        device = self._create_device_with_connection(organization=org)
        device.deactivate()
        device.config.set_status_deactivated()
        operation = UpgradeOperation.objects.create(device=device, batch=batch)
        second_operation = UpgradeOperation.objects.create(device=device, batch=batch)
        delete_url = reverse(
            f"admin:{Organization._meta.app_label}"
            f"_{Organization._meta.model_name}_delete",
            args=[org.pk],
        )
        response = self.client.get(delete_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "This deletion is blocked because one or more upgrade operations are "
            "in progress. Cancel them or wait for them to finish before continuing.",
            count=1,
        )
        self.assertContains(response, "your account doesn't have permission to delete")
        self.assertTrue(Organization.objects.filter(pk=org.pk).exists())
        self.assertTrue(BatchUpgradeOperation.objects.filter(pk=batch.pk).exists())
        self.assertTrue(UpgradeOperation.objects.filter(pk=operation.pk).exists())
        self.assertTrue(
            UpgradeOperation.objects.filter(pk=second_operation.pk).exists()
        )

    def test_build_delete_with_in_progress_operation(self):
        self._login()
        category = self._create_category(name="Cascade Category")
        build = self._create_build(category=category, version="9.9")
        batch = BatchUpgradeOperation.objects.create(build=build, status="success")
        device = self._create_device_with_connection()
        operation = UpgradeOperation.objects.create(device=device, batch=batch)
        second_operation = UpgradeOperation.objects.create(device=device, batch=batch)
        delete_url = reverse(
            f"admin:{Build._meta.app_label}_{Build._meta.model_name}_delete",
            args=[build.pk],
        )
        response = self.client.get(delete_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "This deletion is blocked because one or more upgrade operations are "
            "in progress. Cancel them or wait for them to finish before continuing.",
            count=1,
        )
        self.assertContains(response, "your account doesn't have permission to delete")
        self.assertTrue(Build.objects.filter(pk=build.pk).exists())
        self.assertTrue(BatchUpgradeOperation.objects.filter(pk=batch.pk).exists())
        self.assertTrue(UpgradeOperation.objects.filter(pk=operation.pk).exists())
        self.assertTrue(
            UpgradeOperation.objects.filter(pk=second_operation.pk).exists()
        )


del TestConfigAdmin
