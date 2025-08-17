import asyncio
from time import sleep

import pytest
import swapper
from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from channels.testing import ChannelsLiveServerTestCase, WebsocketCommunicator
from django.conf import settings
from django.test import tag
from django.urls import reverse
from django.utils.module_loading import import_string
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from openwisp_firmware_upgrader.hardware import REVERSE_FIRMWARE_IMAGE_MAP
from openwisp_firmware_upgrader.tests.base import TestUpgraderMixin
from openwisp_firmware_upgrader.websockets import DeviceUpgradeProgressPublisher
from openwisp_utils.tests import SeleniumTestMixin

from ..swapper import load_model

Device = swapper.load_model("config", "Device")
DeviceConnection = swapper.load_model("connection", "DeviceConnection")
UpgradeOperation = load_model("UpgradeOperation")
DeviceFirmware = load_model("DeviceFirmware")
BatchUpgradeOperation = load_model("BatchUpgradeOperation")


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@tag("selenium_tests")
@tag("no_parallel")
class TestRealTimeWebsockets(
    TestUpgraderMixin,
    SeleniumTestMixin,
    ChannelsLiveServerTestCase,
):
    """Test real-time websocket functionality with Selenium"""

    config_app_label = "config"
    firmware_app_label = "firmware_upgrader"
    os = "OpenWrt 19.07-SNAPSHOT r11061-6ffd4d8a4d"
    image_type = REVERSE_FIRMWARE_IMAGE_MAP["YunCore XD3200"]
    browser = "firefox"
    maxDiff = None
    retry_max = 6
    application = import_string(getattr(settings, "ASGI_APPLICATION"))

    def setUp(self):
        org = self._get_org()
        import uuid

        unique_suffix = str(uuid.uuid4())[:8]
        self.admin = self._create_admin(
            username=f"admin_{unique_suffix}",
            password=self.admin_password,
            email=f"admin_{unique_suffix}@example.com",
        )
        self.admin_client = self.client
        self.admin_client.force_login(self.admin)

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

        # Store references for tests
        self.org = org
        self.category = category
        self.build1 = build1
        self.build2 = build2
        self.image1 = image1
        self.image2 = image2
        self.device = device

    def _snooze(self):
        """Allows a bit of time for the UI to update, reduces flakyness"""
        sleep(0.25)

    def _assert_no_js_errors(self):
        browser_logs = []
        for log in self.get_browser_logs():
            # ignore if not console-api
            if log.get("source") != "console-api":
                continue
            else:
                print(log)
                browser_logs.append(log)
        self.assertEqual(browser_logs, [])

    async def _get_communicator(self, admin_client, device_id):
        session_id = admin_client.cookies["sessionid"].value
        communicator = WebsocketCommunicator(
            self.application,
            path=f"ws/firmware-upgrader/device/{device_id}/",
            headers=[
                (
                    b"cookie",
                    f"sessionid={session_id}".encode("ascii"),
                )
            ],
        )
        return communicator

    async def _prepare(self):
        communicator = await self._get_communicator(self.admin_client, self.device.pk)
        path = reverse(
            f"admin:{self.config_app_label}_device_change", args=[self.device.pk]
        )

        self.login(username=self.admin.username, password=self.admin_password)

        self.open(f"{path}#upgradeoperation_set-group")

        self.hide_loading_overlay()

        self.wait_for_visibility(By.ID, "upgradeoperation_set-group")

        WebDriverWait(self.web_driver, 10).until(
            lambda driver: driver.execute_script(
                "return window.upgradeProgressWebSocket && window.upgradeProgressWebSocket.readyState === 1;"
            )
        )

        return communicator

    async def test_real_time_progress_updates(self):
        """Test real-time progress updates via websocket"""

        operation = await database_sync_to_async(UpgradeOperation.objects.create)(
            device=self.device,
            image=self.image2,
            status="in-progress",
            log="Starting upgrade process...",
            progress=25,
        )

        communicator = await self._prepare()

        WebDriverWait(self.web_driver, 2).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".upgrade-progress-text"))
        )

        # Test initial progress bar visibility and components
        progress_container = self.find_element(
            By.CSS_SELECTOR, ".upgrade-status-container"
        )
        self.assertTrue(
            progress_container.is_displayed(), "Progress container should be visible"
        )

        progress_bar = self.find_element(By.CSS_SELECTOR, ".upgrade-progress-bar")
        self.assertTrue(progress_bar.is_displayed(), "Progress bar should be visible")

        progress_fill = self.find_element(By.CSS_SELECTOR, ".upgrade-progress-fill")
        self.assertTrue(progress_fill.is_displayed(), "Progress fill should be visible")

        progress_text = self.find_element(By.CSS_SELECTOR, ".upgrade-progress-text")
        self.assertTrue(progress_text.is_displayed(), "Progress text should be visible")

        # Verify initial state
        initial_progress_text = progress_text.text
        self.assertEqual(initial_progress_text, "25%")

        initial_style = progress_fill.get_attribute("style")
        self.assertIn("width: 25%", initial_style)

        # Update operation to 75% progress
        operation.progress = 75
        operation.log = (
            "Starting upgrade process...\n"
            "Device identity verified successfully\n"
            "Uploading firmware image...\n"
            "Upload progress: 75%"
        )
        await database_sync_to_async(operation.save)()

        # Publish websocket update
        publisher = DeviceUpgradeProgressPublisher(self.device.pk, operation.pk)
        publisher.publish_operation_update(
            {
                "id": str(operation.pk),
                "device": str(self.device.pk),
                "status": "in-progress",
                "log": operation.log,
                "progress": 75,
                "image": str(self.image2.pk),
                "modified": operation.modified.isoformat(),
                "created": operation.created.isoformat(),
            }
        )

        # Verify real-time UI updates
        updated_progress_text = self.find_element(
            By.CSS_SELECTOR, ".upgrade-progress-text"
        ).text
        self.assertEqual(updated_progress_text, "75%")

        updated_progress_fill = self.find_element(
            By.CSS_SELECTOR, ".upgrade-progress-fill"
        )
        updated_style = updated_progress_fill.get_attribute("style")
        self.assertIn("width: 75%", updated_style)

        # Verify log updates in real-time
        log_element = self.find_element(By.CSS_SELECTOR, ".field-log .readonly")
        log_html = log_element.get_attribute("innerHTML")
        self.assertIn("Device identity verified successfully", log_html)
        self.assertIn("Uploading firmware image", log_html)
        self.assertIn("Upload progress: 75%", log_html)

        self._assert_no_js_errors()
        try:
            await communicator.disconnect()
        except (Exception, asyncio.CancelledError):
            pass

    async def test_real_time_status_change_to_success(self):
        """Test real-time status change from in-progress to success"""
        # preparation
        operation = await database_sync_to_async(UpgradeOperation.objects.create)(
            device=self.device,
            image=self.image2,
            status="in-progress",
            log="Starting upgrade process...\nUploading firmware...",
            progress=75,
        )

        communicator = await self._prepare()

        # Wait for initial state
        WebDriverWait(self.web_driver, 2).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".upgrade-progress-text"))
        )

        initial_progress_text = self.find_element(
            By.CSS_SELECTOR, ".upgrade-progress-text"
        ).text
        self.assertEqual(initial_progress_text, "75%")

        # Update operation status to success with realistic log
        operation.status = "success"
        operation.progress = 100
        operation.log = (
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
        await database_sync_to_async(operation.save)()

        # Publish websocket update
        publisher = DeviceUpgradeProgressPublisher(self.device.pk, operation.pk)
        publisher.publish_operation_update(
            {
                "id": str(operation.pk),
                "device": str(self.device.pk),
                "status": "success",
                "log": operation.log,
                "progress": 100,
                "image": str(self.image2.pk),
                "modified": operation.modified.isoformat(),
                "created": operation.created.isoformat(),
            }
        )

        # Verify real-time UI updates for success status
        WebDriverWait(self.web_driver, 5).until(
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

        # Verify comprehensive success log display
        log_element = self.find_element(By.CSS_SELECTOR, ".field-log .readonly")
        log_html = log_element.get_attribute("innerHTML")
        self.assertIn("Connection successful", log_html)
        self.assertIn("Device identity verified", log_html)
        self.assertIn("Sysupgrade test passed", log_html)
        self.assertIn("completed successfully", log_html)

        self._assert_no_js_errors()

        try:
            await communicator.disconnect()
        except (Exception, asyncio.CancelledError):
            pass

    async def test_real_time_log_updates(self):
        """Test real-time log line appending during upgrade"""
        # preparation
        operation = await database_sync_to_async(UpgradeOperation.objects.create)(
            device=self.device,
            image=self.image2,
            status="in-progress",
            log="Starting upgrade process...",
            progress=20,
        )

        communicator = await self._prepare()

        # Wait for initial state
        WebDriverWait(self.web_driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".field-log .readonly"))
        )

        initial_log = self.find_element(
            By.CSS_SELECTOR, ".field-log .readonly"
        ).get_attribute("innerHTML")
        self.assertIn("Starting upgrade process", initial_log)

        # Update operation log
        new_log_line = "Device identity verified successfully"
        operation.log = f"{operation.log}\n{new_log_line}"
        await database_sync_to_async(operation.save)()

        publisher = DeviceUpgradeProgressPublisher(self.device.pk, operation.pk)
        publisher.publish_log(new_log_line, "in-progress")

        # Verify UI update
        updated_log = self.find_element(
            By.CSS_SELECTOR, ".field-log .readonly"
        ).get_attribute("innerHTML")
        self.assertIn("Device identity verified successfully", updated_log)

        self._assert_no_js_errors()
        try:
            await communicator.disconnect()
        except (Exception, asyncio.CancelledError):
            pass

    async def test_real_time_status_change_to_failed(self):
        """Test real-time status change to failed"""
        # preparation
        operation = await database_sync_to_async(UpgradeOperation.objects.create)(
            device=self.device,
            image=self.image2,
            status="in-progress",
            log="Starting upgrade process...",
            progress=50,
        )

        communicator = await self._prepare()

        # Wait for initial state
        WebDriverWait(self.web_driver, 2).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".upgrade-progress-text"))
        )

        operation.status = "failed"
        operation.progress = 50  # Failed operations don't reach 100%
        operation.log = (
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
        await database_sync_to_async(operation.save)()

        # Publish websocket update
        publisher = DeviceUpgradeProgressPublisher(self.device.pk, operation.pk)
        publisher.publish_operation_update(
            {
                "id": str(operation.pk),
                "device": str(self.device.pk),
                "status": "failed",
                "log": operation.log,
                "progress": 50,
                "image": str(self.image2.pk),
                "modified": operation.modified.isoformat(),
                "created": operation.created.isoformat(),
            }
        )

        WebDriverWait(self.web_driver, 5).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, ".upgrade-progress-fill.failed")
            )
        )

        progress_fill = self.find_element(
            By.CSS_SELECTOR, ".upgrade-progress-fill.failed"
        )
        class_list = progress_fill.get_attribute("class")
        self.assertIn("failed", class_list)

        log_element = self.find_element(By.CSS_SELECTOR, ".field-log .readonly")
        log_html = log_element.get_attribute("innerHTML")
        self.assertIn("Image check failed", log_html)
        self.assertIn("aborting upgrade", log_html)
        self.assertIn("operation failed", log_html)
        self.assertIn("Starting non critical services", log_html)

        self._assert_no_js_errors()

        try:
            await communicator.disconnect()
        except (Exception, asyncio.CancelledError):
            pass

    async def test_real_time_status_change_to_aborted(self):
        """Test real-time status change to aborted"""
        # preparation
        operation = await database_sync_to_async(UpgradeOperation.objects.create)(
            device=self.device,
            image=self.image2,
            status="in-progress",
            log="Starting upgrade process...",
            progress=30,
        )

        communicator = await self._prepare()

        # Wait for initial state
        WebDriverWait(self.web_driver, 2).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".upgrade-progress-text"))
        )

        operation.status = "aborted"
        operation.progress = 30  # Aborted operations stop at current progress
        operation.log = (
            "Connection successful, starting upgrade...\n"
            "Could not read device UUID from configuration\n"
            'Device UUID mismatch: expected "12345678-1234-1234-1234-123456789abc", '
            'found "87654321-4321-4321-4321-cba987654321" in device configuration\n'
            "Upgrade operation aborted for security reasons\n"
            "Starting non critical services again...\n"
            "Non critical services started, aborting upgrade."
        )
        await database_sync_to_async(operation.save)()

        # Publish websocket update
        publisher = DeviceUpgradeProgressPublisher(self.device.pk, operation.pk)
        publisher.publish_operation_update(
            {
                "id": str(operation.pk),
                "device": str(self.device.pk),
                "status": "aborted",
                "log": operation.log,
                "progress": 30,
                "image": str(self.image2.pk),
                "modified": operation.modified.isoformat(),
                "created": operation.created.isoformat(),
            }
        )

        log_element = self.find_element(By.CSS_SELECTOR, ".field-log .readonly")
        log_html = log_element.get_attribute("innerHTML")
        self.assertIn("UUID mismatch", log_html)
        self.assertIn("Could not read device UUID", log_html)
        self.assertIn("aborted for security reasons", log_html)
        self.assertIn("aborting upgrade", log_html)

        self._assert_no_js_errors()

        try:
            await communicator.disconnect()
        except (Exception, asyncio.CancelledError):
            pass
