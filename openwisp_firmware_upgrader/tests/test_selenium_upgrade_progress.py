import time
from unittest.mock import patch

import swapper
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import tag
from django.urls.base import reverse
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from openwisp_firmware_upgrader.hardware import REVERSE_FIRMWARE_IMAGE_MAP
from openwisp_firmware_upgrader.tests.base import TestUpgraderMixin
from openwisp_utils.tests import SeleniumTestMixin, capture_any_output

from ..swapper import load_model

Device = swapper.load_model("config", "Device")
UpgradeOperation = load_model("UpgradeOperation")
DeviceFirmware = load_model("DeviceFirmware")


@tag("selenium_tests")
class TestUpgradeProgressJs(
    TestUpgraderMixin, SeleniumTestMixin, StaticLiveServerTestCase
):
    config_app_label = "config"
    firmware_app_label = "firmware_upgrader"
    os = "OpenWrt 19.07-SNAPSHOT r11061-6ffd4d8a4d"
    image_type = REVERSE_FIRMWARE_IMAGE_MAP["YunCore XD3200"]

    def _set_up_env(self):
        org = self._get_org()
        category = self._get_category(organization=org)
        build = self._create_build(category=category, version="1.0", os=self.os)
        image = self._create_firmware_image(build=build, type=self.image_type)
        self._create_credentials(auto_add=True, organization=org)
        device = self._create_device(
            os=self.os, model=image.boards[0], organization=org
        )
        self._create_config(device=device)
        return org, category, build, image, device

    def setUp(self):
        self.admin = self._create_admin(
            username=self.admin_username, password=self.admin_password
        )

    @capture_any_output()
    def test_progress_bar_visibility(self):
        """Test that progress bar is visible for in-progress operations"""
        org, category, build, image, device = self._set_up_env()

        # Create an in-progress upgrade operation
        UpgradeOperation.objects.create(
            device=device,
            image=image,
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

        # Wait for upgrade operations section to load
        self.wait_for_visibility(By.ID, "upgradeoperation_set-group")

        # Wait for JavaScript to initialize and create progress bars
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
        org, category, build, image, device = self._set_up_env()

        UpgradeOperation.objects.create(
            device=device,
            image=image,
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

        # Check for success status
        status_element = self.find_element(By.CSS_SELECTOR, ".upgrade-status-success")
        self.assertEqual(status_element.text, "success")

        # Check progress is 100%
        progress_text = self.find_element(By.CSS_SELECTOR, ".upgrade-progress-text")
        self.assertEqual(progress_text.text, "100%")

        # Check progress bar is full (100% width)
        progress_fill = self.find_element(
            By.CSS_SELECTOR, ".upgrade-progress-fill.success"
        )
        style = progress_fill.get_attribute("style")
        self.assertIn("width: 100%", style)

    @capture_any_output()
    def test_progress_bar_failed(self):
        """Test progress bar shows red color for failed status"""
        org, category, build, image, device = self._set_up_env()

        UpgradeOperation.objects.create(
            device=device, image=image, status="failed", log="Upgrade failed with error"
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
        org, category, build, image, device = self._set_up_env()

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
            device=device, image=image, status="success", log=success_log
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

        # Wait for JavaScript to process logs
        WebDriverWait(self.web_driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".field-log .readonly"))
        )

        # Check log content is displayed
        log_element = self.find_element(By.CSS_SELECTOR, ".field-log .readonly")
        log_html = log_element.get_attribute("innerHTML")

        # Verify log content contains success messages
        self.assertIn("Connection successful", log_html)
        self.assertIn("Device identity verified", log_html)
        self.assertIn("Sysupgrade test passed", log_html)
        self.assertIn("completed successfully", log_html)

    @capture_any_output()
    def test_failed_log_display(self):
        """Test that failed logs are properly displayed with error messages"""
        org, category, build, image, device = self._set_up_env()
        failed_log = (
            "Connection successful, starting upgrade...\n"
            "Device identity verified successfully\n"
            "Image checksum file not found, proceeding with the upload of the new image...\n"
            "The image size (12.3 MiB) is greater than the available memory on the system (8.1 MiB).\n"
            "For this reason the upgrade procedure will try to free up memory by stopping non critical services.\n"
            "Enough available memory was freed up on the system (11.2 MiB)!\n"
            "Proceeding to upload of the image file...\n"
            "Sysupgrade test failed: Image check failed\n"
            "Starting non critical services again...\n"
            "Non critical services started, aborting upgrade.\n"
            "Upgrade operation failed"
        )

        UpgradeOperation.objects.create(
            device=device, image=image, status="failed", log=failed_log
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
        org, category, build, image, device = self._set_up_env()

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
            device=device, image=image, status="aborted", log=aborted_log
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
