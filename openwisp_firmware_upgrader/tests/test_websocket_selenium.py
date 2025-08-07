import json
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
        # Create admin with unique username to avoid conflicts
        import uuid

        unique_suffix = str(uuid.uuid4())[:8]
        self.admin = self._create_admin(
            username=f"admin_{unique_suffix}",
            password=self.admin_password,
            email=f"admin_{unique_suffix}@example.com",
        )
        self.admin_client = self.client
        self.admin_client.force_login(self.admin)

        # Create test environment
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
            if log["source"] != "console-api":
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
        connected, _ = await communicator.connect()
        assert connected is True

        path = reverse(
            f"admin:{self.config_app_label}_device_change", args=[self.device.pk]
        )
        self.login()
        self.open(f"{path}#upgradeoperation_set-group")
        self.hide_loading_overlay()

        # Wait for the page to load and elements to be visible
        self.wait_for_visibility(By.ID, "upgradeoperation_set-group")

        # Wait for websocket connection to be established
        WebDriverWait(self.web_driver, 10).until(
            lambda driver: driver.execute_script(
                "return window.upgradeProgressWebSocket && window.upgradeProgressWebSocket.readyState === 1;"
            )
        )

        return communicator

    async def test_real_time_progress_updates(self):
        """Test real-time progress updates via websocket"""
        # preparation
        operation = await database_sync_to_async(UpgradeOperation.objects.create)(
            device=self.device,
            image=self.image2,
            status="in-progress",
            log="Starting upgrade process...",
            progress=25,
        )

        communicator = await self._prepare()

        # Wait for initial state
        WebDriverWait(self.web_driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".upgrade-progress-text"))
        )

        initial_progress_text = self.find_element(
            By.CSS_SELECTOR, ".upgrade-progress-text"
        ).text
        self.assertEqual(initial_progress_text, "25%")

        # Update operation
        operation.progress = 75
        operation.log = (
            "Starting upgrade process...\nUploading firmware image...\nProgress: 75%"
        )
        await database_sync_to_async(operation.save)()

        # Publish websocket update
        from openwisp_firmware_upgrader.websockets import DeviceUpgradeProgressPublisher

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

        message = await communicator.receive_json_from()
        self._snooze()

        # Verify UI update
        progress_text = self.find_element(
            By.CSS_SELECTOR, ".upgrade-progress-text"
        ).text
        self.assertEqual(progress_text, "75%")

        progress_fill = self.find_element(By.CSS_SELECTOR, ".upgrade-progress-fill")
        style = progress_fill.get_attribute("style")
        self.assertIn("width: 75%", style)

        log_element = self.find_element(By.CSS_SELECTOR, ".field-log .readonly")
        log_html = log_element.get_attribute("innerHTML")
        self.assertIn("Uploading firmware image", log_html)
        self.assertIn("Progress: 75%", log_html)

        self._assert_no_js_errors()
        await communicator.disconnect()

    async def test_real_time_status_change(self):
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
        WebDriverWait(self.web_driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".upgrade-progress-text"))
        )

        initial_progress_text = self.find_element(
            By.CSS_SELECTOR, ".upgrade-progress-text"
        ).text
        self.assertEqual(initial_progress_text, "75%")

        # Update operation status
        operation.status = "success"
        operation.progress = 100
        operation.log = "Starting upgrade process...\nUploading firmware...\nUpgrade completed successfully!"
        await database_sync_to_async(operation.save)()

        # Publish websocket update
        from openwisp_firmware_upgrader.websockets import DeviceUpgradeProgressPublisher

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

        message = await communicator.receive_json_from()
        self._snooze()

        # Verify UI update
        progress_text = self.find_element(
            By.CSS_SELECTOR, ".upgrade-progress-text"
        ).text
        self.assertEqual(progress_text, "100%")

        progress_fill = self.find_element(
            By.CSS_SELECTOR, ".upgrade-progress-fill.success"
        )
        style = progress_fill.get_attribute("style")
        self.assertIn("width: 100%", style)

        log_element = self.find_element(By.CSS_SELECTOR, ".field-log .readonly")
        log_html = log_element.get_attribute("innerHTML")
        self.assertIn("Upgrade completed successfully!", log_html)

        self._assert_no_js_errors()
        await communicator.disconnect()

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

        # Publish websocket update
        from openwisp_firmware_upgrader.websockets import DeviceUpgradeProgressPublisher

        publisher = DeviceUpgradeProgressPublisher(self.device.pk, operation.pk)
        publisher.publish_log(new_log_line, "in-progress")

        message = await communicator.receive_json_from()
        self._snooze()

        # Verify UI update
        updated_log = self.find_element(
            By.CSS_SELECTOR, ".field-log .readonly"
        ).get_attribute("innerHTML")
        self.assertIn("Device identity verified successfully", updated_log)

        self._assert_no_js_errors()
        await communicator.disconnect()
