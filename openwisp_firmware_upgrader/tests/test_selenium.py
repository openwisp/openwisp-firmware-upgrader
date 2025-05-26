from unittest.mock import patch

import swapper
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.management import call_command
from django.test import tag
from django.urls.base import reverse
from reversion.models import Version
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

from openwisp_firmware_upgrader.hardware import REVERSE_FIRMWARE_IMAGE_MAP
from openwisp_firmware_upgrader.tests.base import TestUpgraderMixin
from openwisp_utils.tests import SeleniumTestMixin, capture_any_output

from ..swapper import load_model
from ..upgraders.openwisp import OpenWrt

Device = swapper.load_model("config", "Device")
DeviceConnection = swapper.load_model("connection", "DeviceConnection")
UpgradeOperation = load_model("UpgradeOperation")
DeviceFirmware = load_model("DeviceFirmware")
BatchUpgradeOperation = load_model("BatchUpgradeOperation")


@tag("selenium_tests")
class TestDeviceAdmin(TestUpgraderMixin, SeleniumTestMixin, StaticLiveServerTestCase):
    config_app_label = "config"
    firmware_app_label = "firmware_upgrader"
    os = "OpenWrt 19.07-SNAPSHOT r11061-6ffd4d8a4d"
    image_type = REVERSE_FIRMWARE_IMAGE_MAP["YunCore XD3200"]

    def _set_up_env(self):
        org = self._get_org()
        category = self._get_category(organization=org)
        build1 = self._create_build(category=category, version="0.1", os=self.os)
        build2 = self._create_build(
            category=category, version="0.2", os="OpenWrt 21.03"
        )
        image1 = self._create_firmware_image(build=build1, type=self.image_type)
        image2 = self._create_firmware_image(build=build2, type=self.image_type)
        self._create_credentials(auto_add=True, organization=org)
        device = self._create_device(
            os=self.os, model=image2.boards[0], organization=org
        )
        self._create_config(device=device)
        return org, category, build1, build2, image1, image2, device

    def setUp(self):
        self.admin = self._create_admin(
            username=self.admin_username, password=self.admin_password
        )

    def _get_device_firmware_dropdown_select(self):
        select_element = self.find_element(By.ID, "id_devicefirmware-0-image")
        return Select(select_element)

    @capture_any_output()
    def test_restoring_deleted_device(self):
        org = self._get_org()
        category = self._get_category(organization=org)
        build = self._create_build(category=category, version="0.1", os=self.os)
        image = self._create_firmware_image(build=build, type=self.image_type)
        self._create_credentials(auto_add=True, organization=org)
        device = self._create_device(
            os=self.os, model=image.boards[0], organization=org
        )
        config = self._create_config(device=device)
        self.assertEqual(Device.objects.count(), 1)
        self.assertEqual(DeviceConnection.objects.count(), 1)
        self.assertEqual(DeviceFirmware.objects.count(), 1)

        call_command("createinitialrevisions")

        self.login()
        device.deactivate()
        config.set_status_deactivated()
        # Delete the device
        self.open(
            reverse(f"admin:{self.config_app_label}_device_delete", args=[device.id])
        )
        self.find_element(By.CSS_SELECTOR, '#content form input[type="submit"]').click()
        self.assertEqual(Device.objects.count(), 0)
        self.assertEqual(DeviceConnection.objects.count(), 0)
        self.assertEqual(DeviceFirmware.objects.count(), 0)

        version_obj = Version.objects.get_deleted(model=Device).first()

        # Restore deleted device
        self.open(
            reverse(
                f"admin:{self.config_app_label}_device_recover", args=[version_obj.id]
            )
        )
        self.wait_for_invisibility(By.ID, "command_set-group")
        self.wait_for_visibility(
            By.XPATH, '//*[@id="device_form"]/div/div[1]/input[1]'
        ).click()
        try:
            WebDriverWait(self.web_driver, 5).until(
                EC.url_to_be(f"{self.live_server_url}/admin/config/device/")
            )
        except TimeoutException:
            self.fail("Deleted device was not restored")

        self.assertEqual(Device.objects.count(), 1)
        self.assertEqual(DeviceConnection.objects.count(), 1)
        self.assertEqual(DeviceFirmware.objects.count(), 1)

    @capture_any_output()
    @patch(
        "openwisp_firmware_upgrader.upgraders.openwrt.OpenWrt.upgrade",
        return_value=True,
    )
    @patch(
        "openwisp_controller.connection.models.DeviceConnection.connect",
        return_value=True,
    )
    def test_device_firmware_upgrade_options(self, *args):
        def save_device():
            self.find_element(
                by=By.XPATH, value='//*[@id="device_form"]/div/div[1]/input[3]'
            ).click()
            self.wait_for_visibility(By.CSS_SELECTOR, "#devicefirmware-group")
            self.hide_loading_overlay()

        _, _, _, _, _, image, device = self._set_up_env()
        self.login()
        self.open(
            "{}#devicefirmware-group".format(
                reverse(
                    f"admin:{self.config_app_label}_device_change", args=[device.id]
                )
            )
        )
        self.hide_loading_overlay()
        # JSONSchema Editor should not be rendered without a change in the image field
        self.wait_for_invisibility(
            By.CSS_SELECTOR, "#devicefirmware-group .jsoneditor-wrapper"
        )
        image_select = self._get_device_firmware_dropdown_select()
        image_select.select_by_value(str(image.pk))
        # JSONSchema configuration editor should not be rendered
        self.wait_for_invisibility(
            By.XPATH,
            '//*[@id="id_devicefirmware-0-upgrade_options_jsoneditor"]/div/h3/span[4]/input',
        )
        # Select "None" image should hide JSONSchema Editor
        image_select.select_by_value("")
        self.wait_for_invisibility(
            By.CSS_SELECTOR, "#id_devicefirmware-0-upgrade_options_jsoneditor"
        )

        # Select "build2" image
        image_select.select_by_value(str(image.pk))
        # Enable '-c' option
        self.find_element(
            by=By.XPATH,
            value='//*[@id="id_devicefirmware-0-upgrade_options_jsoneditor"]'
            "/div/div[2]/div/div/div[1]/div/div[1]/label/input",
        ).click()
        # Enable '-F' option
        self.find_element(
            by=By.XPATH,
            value='//*[@id="id_devicefirmware-0-upgrade_options_jsoneditor"]'
            "/div/div[2]/div/div/div[7]/div/div[1]/label/input",
        ).click()
        save_device()

        # Delete DeviceFirmware
        self.find_element(By.CSS_SELECTOR, "#id_devicefirmware-0-DELETE").click()
        save_device()

        # When adding firmware to the device for the first time,
        # JSONSchema editor should be rendered only when the image
        # is selected
        self.find_element(
            by=By.XPATH, value='//*[@id="devicefirmware-group"]/fieldset/div[2]/a'
        ).click()
        # JSONSchema Editor should not be rendered without a change in the image field
        self.wait_for_invisibility(
            By.CSS_SELECTOR, "#devicefirmware-group .jsoneditor-wrapper"
        )
        image_select = self._get_device_firmware_dropdown_select()
        image_select.select_by_index(1)
        self.wait_for_visibility(
            By.CSS_SELECTOR, "#devicefirmware-group .jsoneditor-wrapper"
        )
        save_device()

    @capture_any_output()
    @patch(
        "openwisp_firmware_upgrader.upgraders.openwrt.OpenWrt.upgrade",
        return_value=True,
    )
    @patch(
        "openwisp_controller.connection.models.DeviceConnection.connect",
        return_value=True,
    )
    def test_batch_upgrade_upgrade_options(self, *args):
        _, _, _, build2, _, _, _ = self._set_up_env()
        self.login()
        self.open(
            reverse(f"admin:{self.firmware_app_label}_build_change", args=[build2.id])
        )
        # Launch mass upgrade operation
        self.find_element(
            by=By.CSS_SELECTOR,
            value='.title-wrapper .object-tools form button[type="submit"]',
        ).click()

        # Ensure JSONSchema form is rendered
        self.wait_for_visibility(By.CSS_SELECTOR, ".jsoneditor-wrapper")
        # JSONSchema configuration editor should not be rendered
        self.wait_for_invisibility(
            By.XPATH,
            '//*[@id="id_devicefirmware-0-upgrade_options_jsoneditor"]/div/h3/span[4]/input',
        )
        # Disable -c flag
        self.find_element(
            by=By.XPATH,
            value='//*[@id="id_upgrade_options_jsoneditor"]/div/div[2]/div/div/div[1]/div/div[1]/label/input',
        ).click()
        # Enable -n flag
        self.find_element(
            by=By.XPATH,
            value='//*[@id="id_upgrade_options_jsoneditor"]/div/div[2]/div/div/div[3]/div/div[1]/label/input',
        ).click()
        # Upgrade all devices
        self.find_element(by=By.CSS_SELECTOR, value='input[name="upgrade_all"]').click()
        try:
            WebDriverWait(self.web_driver, 5).until(
                EC.url_contains("batchupgradeoperation")
            )
        except TimeoutException:
            self.fail("User was not redirected to Mass upgrade operations page")
        self.assertEqual(
            BatchUpgradeOperation.objects.filter(
                upgrade_options={
                    "c": False,
                    "o": False,
                    "n": True,
                    "u": False,
                    "p": False,
                    "k": False,
                    "F": False,
                }
            ).count(),
            1,
        )
        self.assertEqual(
            UpgradeOperation.objects.filter(
                upgrade_options={
                    "c": False,
                    "o": False,
                    "n": True,
                    "u": False,
                    "p": False,
                    "k": False,
                    "F": False,
                }
            ).count(),
            1,
        )

    @capture_any_output()
    @patch(
        "openwisp_firmware_upgrader.upgraders.openwrt.OpenWrt.upgrade",
        return_value=True,
    )
    @patch(
        "openwisp_controller.connection.models.DeviceConnection.connect",
        return_value=True,
    )
    @patch.object(OpenWrt, "SCHEMA", None)
    def test_upgrader_with_unsupported_upgrade_options(self, *args):
        org, category, build1, build2, image1, image2, device = self._set_up_env()
        self.login()

        with self.subTest("Test DeviceFirmware"):
            self.open(
                "{}#devicefirmware-group".format(
                    reverse(
                        f"admin:{self.config_app_label}_device_change", args=[device.id]
                    )
                )
            )
            self.hide_loading_overlay()
            image_select = self._get_device_firmware_dropdown_select()
            image_select.select_by_value(str(image2.pk))
            # Ensure JSONSchema editor is not rendered because
            # the upgrader does not define a schema
            self.wait_for_invisibility(
                By.CSS_SELECTOR, "#devicefirmware-group .jsoneditor-wrapper"
            )
            self.find_element(
                by=By.XPATH, value='//*[@id="device_form"]/div/div[1]/input[3]'
            ).click()
            self.assertEqual(
                UpgradeOperation.objects.filter(upgrade_options={}).count(), 1
            )
        DeviceFirmware.objects.all().delete()
        UpgradeOperation.objects.all().delete()

        with self.subTest("Test BatchUpgradeOperation"):
            self.open(
                reverse(
                    f"admin:{self.firmware_app_label}_build_change", args=[build2.id]
                )
            )
            # Launch mass upgrade operation
            self.find_element(
                by=By.CSS_SELECTOR,
                value='.title-wrapper .object-tools form button[type="submit"]',
            ).click()
            # Ensure JSONSchema editor is not rendered because
            # the upgrader does not define a schema
            self.wait_for_invisibility(
                By.CSS_SELECTOR, "#devicefirmware-group .jsoneditor-wrapper"
            )
            # Upgrade all devices
            self.find_element(
                by=By.CSS_SELECTOR, value='input[name="upgrade_all"]'
            ).click()
            self.assertEqual(
                UpgradeOperation.objects.filter(upgrade_options={}).count(), 1
            )
