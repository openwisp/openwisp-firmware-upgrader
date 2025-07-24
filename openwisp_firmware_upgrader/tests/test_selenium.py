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

    @capture_any_output()
    def test_progress_bar_visibility(self):
        """Test that progress bar is visible for in-progress operations"""
        org, category, build1, build2, image1, image2, device = self._set_up_env()

        UpgradeOperation.objects.create(
            device=device,
            image=image2,
            status="in-progress",
            log="Starting upgrade process...",
        )

        self.login()
        self.open(
            "{}#upgradeoperation_set-group".format(
                reverse(
                    f"admin:{self.config_app_label}_device_change", args=[device.id]
                )
            )
        )
        self.hide_loading_overlay()
        self.wait_for_visibility(By.ID, "upgradeoperation_set-group")

        WebDriverWait(self.web_driver, 2).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, ".upgrade-status-container")
            )
        )

        # Test progress bar visibility
        progress_container = self.find_element(
            By.CSS_SELECTOR, ".upgrade-status-container"
        )
        self.assertTrue(progress_container.is_displayed())

        progress_bar = self.find_element(By.CSS_SELECTOR, ".upgrade-progress-bar")
        self.assertTrue(progress_bar.is_displayed())

        progress_fill = self.find_element(By.CSS_SELECTOR, ".upgrade-progress-fill")
        self.assertTrue(progress_fill.is_displayed())

        progress_text = self.find_element(By.CSS_SELECTOR, ".upgrade-progress-text")
        self.assertTrue(progress_text.is_displayed())

    @capture_any_output()
    def test_progress_bar_success(self):
        """Test that progress bar shows 100% for successful operations"""
        org, category, build1, build2, image1, image2, device = self._set_up_env()

        UpgradeOperation.objects.create(
            device=device,
            image=image2,
            status="success",
            log="Upgrade completed successfully",
        )

        self.login()
        self.open(
            "{}#upgradeoperation_set-group".format(
                reverse(
                    f"admin:{self.config_app_label}_device_change", args=[device.id]
                )
            )
        )
        self.hide_loading_overlay()

        self.wait_for_visibility(By.ID, "upgradeoperation_set-group")

        WebDriverWait(self.web_driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".upgrade-status-success"))
        )

        status_element = self.find_element(By.CSS_SELECTOR, ".upgrade-status-success")
        self.assertEqual(status_element.text, "success")

        progress_text = self.find_element(By.CSS_SELECTOR, ".upgrade-progress-text")
        self.assertEqual(progress_text.text, "100%")

        progress_fill = self.find_element(
            By.CSS_SELECTOR, ".upgrade-progress-fill.success"
        )
        style = progress_fill.get_attribute("style")
        self.assertIn("width: 100%", style)

    @capture_any_output()
    def test_progress_bar_failed(self):
        """Test progress bar shows red color for failed status"""
        org, category, build1, build2, image1, image2, device = self._set_up_env()

        UpgradeOperation.objects.create(
            device=device,
            image=image2,
            status="failed",
            log="Upgrade failed with error",
        )

        self.login()
        self.open(
            "{}#upgradeoperation_set-group".format(
                reverse(
                    f"admin:{self.config_app_label}_device_change", args=[device.id]
                )
            )
        )
        self.hide_loading_overlay()

        self.wait_for_visibility(By.ID, "upgradeoperation_set-group")

        WebDriverWait(self.web_driver, 15).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, ".upgrade-progress-fill.failed")
            )
        )

        progress_fill = self.find_element(
            By.CSS_SELECTOR, ".upgrade-progress-fill.failed"
        )
        class_list = progress_fill.get_attribute("class")
        self.assertIn("failed", class_list)

    @capture_any_output()
    def test_success_log_display(self):
        """Test that success logs are properly displayed and formatted"""
        org, category, build1, build2, image1, image2, device = self._set_up_env()

        success_log = (
            "Connection successful, starting upgrade...\n"
            "Device identity verified successfully\n"
            "Image checksum file not found, proceeding with the upload of the new image...\n"
            "The image size (8.5 MiB) is within available memory (64.2 MiB)\n"
            "Sysupgrade test passed successfully, proceeding with the upgrade operation...\n"
            "Upgrade operation in progress...\n"
            "SSH connection closed, will wait 180 seconds before attempting to reconnect...\n"
            "Trying to reconnect to device at 192.168.1.1 (attempt n.1)...\n"
            "Connection re-established successfully\n"
            "Firmware upgrade completed successfully"
        )

        UpgradeOperation.objects.create(
            device=device, image=image2, status="success", log=success_log
        )

        self.login()
        self.open(
            "{}#upgradeoperation_set-group".format(
                reverse(
                    f"admin:{self.config_app_label}_device_change", args=[device.id]
                )
            )
        )
        self.hide_loading_overlay()

        self.wait_for_visibility(By.ID, "upgradeoperation_set-group")

        WebDriverWait(self.web_driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".field-log .readonly"))
        )

        log_element = self.find_element(By.CSS_SELECTOR, ".field-log .readonly")
        log_html = log_element.get_attribute("innerHTML")

        self.assertIn("Connection successful", log_html)
        self.assertIn("Device identity verified", log_html)
        self.assertIn("Sysupgrade test passed", log_html)
        self.assertIn("completed successfully", log_html)

    @capture_any_output()
    def test_failed_log_display(self):
        """Test that failed logs are properly displayed with error messages"""
        org, category, build1, build2, image1, image2, device = self._set_up_env()
        failed_log = (
            "Connection successful, starting upgrade...\n"
            "Device identity verified successfully\n"
            "Image checksum file not found, proceeding with the upload of the new image...\n"
            "The image size (12.3 MiB) is greater than the available memory on the system (8.1 MiB).\n"
            "Enough available memory was freed up on the system (11.2 MiB)!\n"
            "Proceeding to upload of the image file...\n"
            "Sysupgrade test failed: Image check failed\n"
            "Starting non critical services again...\n"
            "Non critical services started, aborting upgrade.\n"
            "Upgrade operation failed"
        )

        UpgradeOperation.objects.create(
            device=device, image=image2, status="failed", log=failed_log
        )

        self.login()
        self.open(
            "{}#upgradeoperation_set-group".format(
                reverse(
                    f"admin:{self.config_app_label}_device_change", args=[device.id]
                )
            )
        )
        self.hide_loading_overlay()

        self.wait_for_visibility(By.ID, "upgradeoperation_set-group")

        WebDriverWait(self.web_driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".field-log .readonly"))
        )

        log_element = self.find_element(By.CSS_SELECTOR, ".field-log .readonly")
        log_html = log_element.get_attribute("innerHTML")

        self.assertIn("Image check failed", log_html)
        self.assertIn("aborting upgrade", log_html)
        self.assertIn("operation failed", log_html)
        self.assertIn("Starting non critical services", log_html)

    @capture_any_output()
    def test_aborted_log_display(self):
        """Test that aborted logs are properly displayed with abort reasons"""
        org, category, build1, build2, image1, image2, device = self._set_up_env()

        aborted_log = (
            "Connection successful, starting upgrade...\n"
            "Could not read device UUID from configuration\n"
            'Device UUID mismatch: expected "12345678-1234-1234-1234-123456789abc", '
            'found "87654321-4321-4321-4321-cba987654321" in device configuration\n'
            "Upgrade operation aborted for security reasons\n"
            "Starting non critical services again...\n"
            "Non critical services started, aborting upgrade."
        )

        UpgradeOperation.objects.create(
            device=device, image=image2, status="aborted", log=aborted_log
        )

        self.login()
        self.open(
            "{}#upgradeoperation_set-group".format(
                reverse(
                    f"admin:{self.config_app_label}_device_change", args=[device.id]
                )
            )
        )
        self.hide_loading_overlay()

        self.wait_for_visibility(By.ID, "upgradeoperation_set-group")

        WebDriverWait(self.web_driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".field-log .readonly"))
        )

        log_element = self.find_element(By.CSS_SELECTOR, ".field-log .readonly")
        log_html = log_element.get_attribute("innerHTML")

        self.assertIn("UUID mismatch", log_html)
        self.assertIn("Could not read device UUID", log_html)
        self.assertIn("aborted for security reasons", log_html)
        self.assertIn("aborting upgrade", log_html)

    @capture_any_output()
    def test_in_progress_upgrade(self):
        """Test detailed in-progress upgrade operation with all visible components"""
        org, category, build1, build2, image1, image2, device = self._set_up_env()

        progress_log = (
            "Connection successful, starting upgrade...\n"
            "Device identity verified successfully\n"
            "Preparing device for upgrade...\n"
            "Upload progress: 25%\n"
            "Upload progress: 50%\n"
            "Upload progress: 75%\n"
            "Upload completed, verifying image...\n"
            "Image verification successful\n"
            "Starting sysupgrade process..."
        )

        UpgradeOperation.objects.create(
            device=device,
            image=image2,
            status="in-progress",
            log=progress_log,
            progress=80,
        )

        self.login()
        self.open(
            "{}#upgradeoperation_set-group".format(
                reverse(
                    f"admin:{self.config_app_label}_device_change", args=[device.id]
                )
            )
        )
        self.hide_loading_overlay()

        self.wait_for_visibility(By.ID, "upgradeoperation_set-group")

        WebDriverWait(self.web_driver, 2).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, ".upgrade-status-container")
            )
        )

        status_container = self.find_element(
            By.CSS_SELECTOR, ".upgrade-status-container"
        )
        self.assertTrue(status_container.is_displayed())

        progress_bar = self.find_element(By.CSS_SELECTOR, ".upgrade-progress-bar")
        self.assertTrue(progress_bar.is_displayed())

        progress_fill = self.find_element(By.CSS_SELECTOR, ".upgrade-progress-fill")
        self.assertTrue(progress_fill.is_displayed())

        progress_text = self.find_element(By.CSS_SELECTOR, ".upgrade-progress-text")
        self.assertTrue(progress_text.is_displayed())

        log_element = self.find_element(By.CSS_SELECTOR, ".field-log .readonly")
        self.assertTrue(log_element.is_displayed())
        log_html = log_element.get_attribute("innerHTML")

        self.assertIn("Connection successful", log_html)
        self.assertIn("Device identity verified", log_html)
        self.assertIn("Preparing device for upgrade", log_html)
        self.assertIn("Upload progress: 25%", log_html)
        self.assertIn("Upload progress: 50%", log_html)
        self.assertIn("Upload progress: 75%", log_html)
        self.assertIn("Upload completed", log_html)
        self.assertIn("Image verification successful", log_html)
        self.assertIn("Starting sysupgrade process", log_html)

    @capture_any_output()
    def test_duplicate_upgrade_abortion(self):
        """Test that attempting duplicate upgrade operations results in abortion"""
        org, category, build1, build2, image1, image2, device = self._set_up_env()

        UpgradeOperation.objects.create(
            device=device,
            image=image2,
            status="in-progress",
            log="First upgrade operation in progress...",
        )

        UpgradeOperation.objects.create(
            device=device,
            image=image2,
            status="aborted",
            log="Another upgrade operation is in progress, aborting...",
        )

        self.login()
        self.open(
            "{}#upgradeoperation_set-group".format(
                reverse(
                    f"admin:{self.config_app_label}_device_change", args=[device.id]
                )
            )
        )
        self.hide_loading_overlay()

        self.wait_for_visibility(By.ID, "upgradeoperation_set-group")

        WebDriverWait(self.web_driver, 2).until(
            EC.presence_of_all_elements_located(
                (By.CSS_SELECTOR, ".upgrade-status-container")
            )
        )

        status_containers = self.find_elements(
            By.CSS_SELECTOR, ".upgrade-status-container"
        )
        self.assertEqual(len(status_containers), 2)

        log_elements = self.find_elements(By.CSS_SELECTOR, ".field-log .readonly")
        self.assertEqual(len(log_elements), 2)

        log_contents = [elem.get_attribute("innerHTML") for elem in log_elements]

        any_contains_abort_message = any(
            "Another upgrade operation is in progress" in content
            for content in log_contents
        )
        self.assertTrue(any_contains_abort_message)

    @capture_any_output()
    def test_multiple_devices_upgrade_operations(self):
        """Test device with multiple upgrade operations showing different statuses"""
        org, category, build1, build2, image1, image2, device = self._set_up_env()

        UpgradeOperation.objects.create(
            device=device,
            image=image1,
            status="success",
            log="First upgrade completed successfully",
        )

        UpgradeOperation.objects.create(
            device=device,
            image=image2,
            status="failed",
            log="Second upgrade failed: connection timeout",
        )

        UpgradeOperation.objects.create(
            device=device,
            image=image2,
            status="in-progress",
            log="Third upgrade in progress...",
        )

        self.login()
        self.open(
            "{}#upgradeoperation_set-group".format(
                reverse(
                    f"admin:{self.config_app_label}_device_change", args=[device.id]
                )
            )
        )
        self.hide_loading_overlay()

        self.wait_for_visibility(By.ID, "upgradeoperation_set-group")

        WebDriverWait(self.web_driver, 2).until(
            EC.presence_of_all_elements_located(
                (By.CSS_SELECTOR, ".upgrade-status-container")
            )
        )

        status_containers = self.find_elements(
            By.CSS_SELECTOR, ".upgrade-status-container"
        )
        self.assertEqual(len(status_containers), 3)

        progress_fills = self.find_elements(By.CSS_SELECTOR, ".upgrade-progress-fill")
        self.assertEqual(len(progress_fills), 3)

        log_elements = self.find_elements(By.CSS_SELECTOR, ".field-log .readonly")
        self.assertEqual(len(log_elements), 3)

        log_contents = [elem.get_attribute("innerHTML") for elem in log_elements]

        any_contains_success = any(
            "completed successfully" in content for content in log_contents
        )
        any_contains_failed = any(
            "connection timeout" in content for content in log_contents
        )
        any_contains_progress = any(
            "in progress" in content for content in log_contents
        )

        self.assertTrue(any_contains_success)
        self.assertTrue(any_contains_failed)
        self.assertTrue(any_contains_progress)
