import uuid
from unittest.mock import patch

import swapper
from channels.testing import ChannelsLiveServerTestCase
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.management import call_command
from django.test import tag
from django.urls import reverse
from reversion.models import Version
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

from openwisp_firmware_upgrader.hardware import REVERSE_FIRMWARE_IMAGE_MAP
from openwisp_firmware_upgrader.tests.base import SeleniumTestMixin, TestUpgraderMixin
from openwisp_firmware_upgrader.websockets import (
    BatchUpgradeProgressPublisher,
    UpgradeProgressPublisher,
)
from openwisp_utils.tests import capture_any_output

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
        _org, _category, _build1, build2, _image1, image2, device = self._set_up_env()
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
            self.wait_for_visibility(By.CSS_SELECTOR, "#devicefirmware-group")
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
    def test_upgrade_cancel_modal(self):
        """Test upgrade cancel modal functionality"""
        org, category, build1, build2, image1, image2, device = self._set_up_env()
        UpgradeOperation.objects.create(
            device=device,
            image=image2,
            status="in-progress",
            log="Upgrade operation in progress...",
            progress=30,
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
        # Wait for upgrade operations section to be visible
        self.wait_for_visibility(By.ID, "upgradeoperation_set-group")
        # Wait for progress bars and status containers to load
        WebDriverWait(self.web_driver, 2).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, ".upgrade-status-container")
            )
        )
        # Wait for cancel button to be present and clickable
        cancel_button = WebDriverWait(self.web_driver, 2).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".upgrade-cancel-btn"))
        )
        # Verify cancel button properties
        self.assertTrue(cancel_button.is_displayed())
        self.assertEqual(cancel_button.text.strip(), "Cancel")
        # Click cancel button to open modal
        self.web_driver.execute_script("arguments[0].click();", cancel_button)
        # Wait for modal to appear
        WebDriverWait(self.web_driver, 2).until(
            EC.visibility_of_element_located((By.ID, "ow-cancel-confirmation-modal"))
        )
        # Verify modal is visible and not hidden
        modal = self.find_element(By.ID, "ow-cancel-confirmation-modal")
        self.assertTrue(modal.is_displayed())
        modal = self.find_element(By.ID, "ow-cancel-confirmation-modal")
        title_element = WebDriverWait(self.web_driver, 2).until(
            EC.presence_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "#ow-cancel-confirmation-modal .ow-cancel-confirmation-title",
                )
            )
        )
        self.assertEqual(title_element.text.strip(), "STOP UPGRADE OPERATION")
        self.assertTrue(title_element.is_displayed())
        # Test closing modal with No button
        no_button = WebDriverWait(self.web_driver, 2).until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "#ow-cancel-confirmation-modal .ow-dialog-close-x")
            )
        )
        self.web_driver.execute_script("arguments[0].click();", no_button)
        # Wait for modal to close
        WebDriverWait(self.web_driver, 2).until(
            EC.invisibility_of_element_located((By.ID, "ow-cancel-confirmation-modal"))
        )
        # Open modal again and confirm (main UI flow)
        cancel_button = WebDriverWait(self.web_driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".upgrade-cancel-btn"))
        )
        self.web_driver.execute_script("arguments[0].click();", cancel_button)

        WebDriverWait(self.web_driver, 10).until(
            EC.visibility_of_element_located((By.ID, "ow-cancel-confirmation-modal"))
        )
        yes_button = WebDriverWait(self.web_driver, 10).until(
            EC.element_to_be_clickable(
                (
                    By.CSS_SELECTOR,
                    "#ow-cancel-confirmation-modal .ow-cancel-btn-confirm",
                )
            )
        )
        self.web_driver.execute_script("arguments[0].click();", yes_button)
        # Modal should close after confirming
        WebDriverWait(self.web_driver, 10).until(
            EC.invisibility_of_element_located((By.ID, "ow-cancel-confirmation-modal"))
        )

    def test_mass_upgrade_confirmation_page_widgets(self):
        """Test mass upgrade confirmation page loads without JS errors and Select2 widgets are initialized"""
        _, _, _, build2, _, _, _ = self._set_up_env()
        self.login()
        self.open(
            reverse(f"admin:{self.firmware_app_label}_build_change", args=[build2.id])
        )
        self.find_element(
            by=By.CSS_SELECTOR,
            value='.title-wrapper .object-tools form button[type="submit"]',
        ).click()
        WebDriverWait(self.web_driver, 10).until(
            EC.presence_of_element_located((By.ID, "id_group"))
        )
        self._assert_no_js_errors()
        self.find_element(By.CSS_SELECTOR, ".select2-container")
        self.assertTrue(
            len(self.web_driver.find_elements(By.CSS_SELECTOR, ".select2-container"))
            >= 2,
            "Both group and location Select2 widgets are initialized",
        )

    @patch(
        "openwisp_firmware_upgrader.upgraders.openwrt.OpenWrt.upgrade",
        return_value=True,
    )
    @patch(
        "openwisp_controller.connection.models.DeviceConnection.connect",
        return_value=True,
    )
    def test_upgrade_operation_admin_no_submit_row(self, *args):
        """Test that UpgradeOperation admin change page does not display submit-row"""
        # Create device firmware and upgrade
        self._create_device_firmware(upgrade=True)
        uo = UpgradeOperation.objects.first()
        self.login()
        self.open(
            reverse(
                f"admin:{self.firmware_app_label}_upgradeoperation_change", args=[uo.pk]
            )
        )
        self.wait_for_invisibility(By.CSS_SELECTOR, ".submit-row")


@tag("selenium_tests")
class TestRealTimeProgress(
    TestUpgraderMixin,
    SeleniumTestMixin,
    ChannelsLiveServerTestCase,
):
    """Test real-time progress functionality with Selenium"""

    config_app_label = "config"
    firmware_app_label = "firmware_upgrader"
    os = "OpenWrt 19.07-SNAPSHOT r11061-6ffd4d8a4d"
    image_type = REVERSE_FIRMWARE_IMAGE_MAP["YunCore XD3200"]
    maxDiff = None

    def setUp(self):
        org = self._get_org()
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
            os=self.os,
            model=image2.boards[0],
            organization=org,
            name=f"test-device-{unique_suffix}",
            mac_address=f"00:11:aa:bb:cc:{unique_suffix[:2]}",
        )
        self._create_config(device=device)
        # Create additional devices for batch testing
        device1 = self._create_device(
            os=self.os,
            model=image2.boards[0],
            organization=org,
            name=f"test-device-1-{unique_suffix}",
            mac_address=f"00:22:bb:cc:dd:{unique_suffix[:2]}",
        )
        device2 = self._create_device(
            os=self.os,
            model=image2.boards[0],
            organization=org,
            name=f"test-device-2-{unique_suffix}",
            mac_address=f"00:33:cc:dd:ee:{unique_suffix[:2]}",
        )
        device3 = self._create_device(
            os=self.os,
            model=image2.boards[0],
            organization=org,
            name=f"test-device-3-{unique_suffix}",
            mac_address=f"00:44:dd:ee:ff:{unique_suffix[:2]}",
        )
        self._create_config(device=device1)
        self._create_config(device=device2)
        self._create_config(device=device3)
        # Store references for tests
        self.org = org
        self.category = category
        self.build1 = build1
        self.build2 = build2
        self.image1 = image1
        self.image2 = image2
        self.device = device
        self.device1 = device1
        self.device2 = device2
        self.device3 = device3

    def _prepare(self):
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

    def _check_progress_text(self, expected_text):
        """Helper method to safely check progress text without stale element issues"""
        # Wait for websocket message to propagate and update DOM
        WebDriverWait(self.web_driver, 10).until(
            EC.text_to_be_present_in_element(
                (By.CSS_SELECTOR, ".batch-main-progress .upgrade-progress-text"),
                expected_text,
            )
        )

    def _check_operation_progress(self, status_class, progress_width):
        """Helper method to safely check individual operation progress without stale element issues"""
        try:
            containers = self.find_elements(
                By.CSS_SELECTOR, "#result_list .upgrade-status-container"
            )
            for container in containers:
                progress_fill = container.find_element(
                    By.CSS_SELECTOR, ".upgrade-progress-fill"
                )
                if status_class in progress_fill.get_attribute(
                    "class"
                ) and progress_width in progress_fill.get_attribute("style"):
                    return True
            return False
        except (StaleElementReferenceException, NoSuchElementException):
            return False

    def _check_row_count(self, expected_count):
        """Helper method to safely check row count without stale element issues"""
        try:
            rows = self.find_elements(By.CSS_SELECTOR, "#result_list tbody tr")
            return len(rows) == expected_count
        except (StaleElementReferenceException, NoSuchElementException):
            return False

    def _prepare_batch(self, batch_operation):
        """Navigate to batch upgrade page and wait for websocket connection"""
        path = reverse(
            f"admin:{self.firmware_app_label}_batchupgradeoperation_change",
            args=[batch_operation.pk],
        )
        self.login(username=self.admin.username, password=self.admin_password)
        self.open(path)
        self.wait_for_visibility(By.ID, "result_list")
        WebDriverWait(self.web_driver, 10).until(
            lambda driver: driver.execute_script(
                "return window.batchUpgradeProgressWebSocket && "
                "window.batchUpgradeProgressWebSocket.readyState === 1;"
            )
        )

    def test_progress_updates(self):
        """Test real-time progress updates via websocket"""
        operation = UpgradeOperation.objects.create(
            device=self.device,
            image=self.image2,
            status="in-progress",
            log="Starting upgrade process...",
            progress=25,
        )
        self._prepare()
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
        WebDriverWait(self.web_driver, 10).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, ".upgrade-progress-bar"))
        )
        WebDriverWait(self.web_driver, 10).until(
            EC.visibility_of_element_located(
                (By.CSS_SELECTOR, ".upgrade-progress-fill[style*='width: 25%']")
            )
        )
        progress_text = WebDriverWait(self.web_driver, 10).until(
            EC.visibility_of_element_located(
                (By.CSS_SELECTOR, ".upgrade-progress-text")
            )
        )
        # Verify initial state
        initial_progress_text = progress_text.text
        self.assertEqual(initial_progress_text, "25%")
        # Update operation to 75% progress
        operation.progress = 75
        operation.log = (
            "Starting upgrade process...\n"
            "Device identity verified successfully\n"
            "Uploading firmware image...\n"
            "Upload progress: 75%"
        )
        operation.save()
        # Publish websocket update
        publisher = UpgradeProgressPublisher(self.device.pk, operation.pk)
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
        WebDriverWait(self.web_driver, 5).until(
            EC.text_to_be_present_in_element(
                (By.CSS_SELECTOR, ".upgrade-progress-text"), "75%"
            )
        )
        WebDriverWait(self.web_driver, 5).until(
            EC.text_to_be_present_in_element_attribute(
                (By.CSS_SELECTOR, ".upgrade-progress-fill"), "style", "width: 75%"
            )
        )
        # Verify log updates in real-time
        WebDriverWait(self.web_driver, 5).until(
            lambda driver: all(
                text
                in driver.find_element(
                    By.CSS_SELECTOR, ".field-log .readonly"
                ).get_attribute("innerHTML")
                for text in [
                    "Device identity verified successfully",
                    "Uploading firmware image",
                    "Upload progress: 75%",
                ]
            )
        )
        self._assert_no_js_errors()

    def test_status_change_to_success(self):
        """Test real-time status change from in-progress to success"""
        # preparation
        operation = UpgradeOperation.objects.create(
            device=self.device,
            image=self.image2,
            status="in-progress",
            log="Starting upgrade process...\nUploading firmware...",
            progress=75,
        )
        self._prepare()
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
        operation.save()
        # Publish websocket update
        publisher = UpgradeProgressPublisher(self.device.pk, operation.pk)
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

    def test_log_updates(self):
        """Test real-time log line appending during upgrade"""
        # preparation
        operation = UpgradeOperation.objects.create(
            device=self.device,
            image=self.image2,
            status="in-progress",
            log="Starting upgrade process...",
            progress=20,
        )
        self._prepare()
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
        operation.save()
        # Verify UI update
        updated_log = self.find_element(
            By.CSS_SELECTOR, ".field-log .readonly"
        ).get_attribute("innerHTML")
        self.assertIn("Device identity verified successfully", updated_log)
        self._assert_no_js_errors()

    def test_status_change_to_failed(self):
        """Test real-time status change to failed"""
        # preparation
        operation = UpgradeOperation.objects.create(
            device=self.device,
            image=self.image2,
            status="in-progress",
            log="Starting upgrade process...",
            progress=50,
        )
        self._prepare()
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
        operation.save()
        # Publish websocket update
        publisher = UpgradeProgressPublisher(self.device.pk, operation.pk)
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

    def test_status_change_to_aborted(self):
        """Test real-time status change to aborted"""
        # preparation
        operation = UpgradeOperation.objects.create(
            device=self.device,
            image=self.image2,
            status="in-progress",
            log="Starting upgrade process...",
            progress=30,
        )
        self._prepare()
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
        operation.save()
        # Publish websocket update
        publisher = UpgradeProgressPublisher(self.device.pk, operation.pk)
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
        # Wait for log updates with explicit waits
        WebDriverWait(self.web_driver, 10).until(
            lambda driver: all(
                text
                in driver.find_element(
                    By.CSS_SELECTOR, ".field-log .readonly"
                ).get_attribute("innerHTML")
                for text in [
                    "UUID mismatch",
                    "Could not read device UUID",
                    "aborted for security reasons",
                    "aborting upgrade",
                ]
            )
        )
        self._assert_no_js_errors()

    def test_batch_main_progress_bar_updates(self):
        """Test batch main progress bar updates via websocket"""
        batch_operation = BatchUpgradeOperation.objects.create(
            build=self.build2, status="in-progress"
        )
        UpgradeOperation.objects.create(
            device=self.device1,
            image=self.image2,
            batch=batch_operation,
            status="in-progress",
            progress=25,
        )
        UpgradeOperation.objects.create(
            device=self.device2,
            image=self.image2,
            batch=batch_operation,
            status="in-progress",
            progress=0,
        )
        self._prepare_batch(batch_operation)
        WebDriverWait(self.web_driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".batch-main-progress"))
        )
        main_progress_element = self.find_element(
            By.CSS_SELECTOR, ".batch-main-progress"
        )
        self.assertTrue(
            main_progress_element.is_displayed(), "Main progress should be visible"
        )
        publisher = BatchUpgradeProgressPublisher(batch_operation.pk)
        publisher.publish_batch_status(status="in-progress", completed=1, total=2)
        self._check_progress_text("50%")
        progress_fill = self.find_element(
            By.CSS_SELECTOR, ".batch-main-progress .upgrade-progress-fill"
        )
        style = progress_fill.get_attribute("style")
        self.assertIn("width: 50%", style)
        publisher.publish_batch_status(status="success", completed=2, total=2)
        self._check_progress_text("100%")
        WebDriverWait(self.web_driver, 10).until(
            EC.presence_of_element_located(
                (
                    By.CSS_SELECTOR,
                    ".batch-main-progress .upgrade-progress-fill.completed-successfully",
                )
            )
        )
        WebDriverWait(self.web_driver, 10).until(
            EC.presence_of_element_located(
                (
                    By.CSS_SELECTOR,
                    ".batch-main-progress"
                    " .upgrade-progress-fill.completed-successfully[style*='width: 100%']",
                )
            )
        )
        progress_fill = self.find_element(
            By.CSS_SELECTOR,
            ".batch-main-progress .upgrade-progress-fill.completed-successfully",
        )
        style = progress_fill.get_attribute("style")
        self.assertIn("width: 100%", style)
        self._assert_no_js_errors()

    def test_individual_operation_progress_updates(self):
        """Test individual operation progress updates within batch upgrade"""
        batch_operation = BatchUpgradeOperation.objects.create(
            build=self.build2, status="in-progress"
        )
        operation1 = UpgradeOperation.objects.create(
            device=self.device1,
            image=self.image2,
            batch=batch_operation,
            status="in-progress",
            progress=10,
        )
        UpgradeOperation.objects.create(
            device=self.device2,
            image=self.image2,
            batch=batch_operation,
            status="in-progress",
            progress=0,
        )
        self._prepare_batch(batch_operation)
        status_containers = WebDriverWait(self.web_driver, 5).until(
            EC.presence_of_all_elements_located(
                (By.CSS_SELECTOR, "#result_list .status-cell .upgrade-status-container")
            )
        )
        self.assertEqual(len(status_containers), 2)
        publisher = BatchUpgradeProgressPublisher(batch_operation.pk)
        device_info = {
            "device_id": self.device1.pk,
            "device_name": self.device1.name,
            "image_name": str(self.image2),
        }
        publisher.publish_operation_progress(
            operation_id=str(operation1.pk),
            status="in-progress",
            progress=50,
            modified=operation1.modified,
            device_info=device_info,
        )
        # Wait for websocket message to propagate and update individual operation progress
        WebDriverWait(self.web_driver, 10).until(
            lambda driver: self._check_operation_progress("in-progress", "width: 50%")
        )
        publisher.publish_operation_progress(
            operation_id=str(operation1.pk),
            status="success",
            progress=100,
            modified=operation1.modified,
            device_info=device_info,
        )
        WebDriverWait(self.web_driver, 10).until(
            lambda driver: self._check_operation_progress("success", "width: 100%")
        )
        self._assert_no_js_errors()

    def test_batch_completion_with_mixed_results(self):
        """Test batch completion with partial success scenario"""
        batch_operation = BatchUpgradeOperation.objects.create(
            build=self.build2, status="in-progress"
        )
        UpgradeOperation.objects.create(
            device=self.device1,
            image=self.image2,
            batch=batch_operation,
            status="success",
            progress=100,
        )
        UpgradeOperation.objects.create(
            device=self.device2,
            image=self.image2,
            batch=batch_operation,
            status="failed",
            progress=45,
        )
        self._prepare_batch(batch_operation)
        WebDriverWait(self.web_driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".batch-main-progress"))
        )
        publisher = BatchUpgradeProgressPublisher(batch_operation.pk)
        publisher.publish_batch_status(status="failed", total=2, completed=2)
        WebDriverWait(self.web_driver, 10).until(
            EC.visibility_of_element_located(
                (
                    By.CSS_SELECTOR,
                    ".batch-main-progress .upgrade-progress-fill.partial-success[style*='width: 100%']",
                )
            )
        )
        status_field = self.find_element(By.CSS_SELECTOR, ".field-status .readonly")
        status_text = status_field.get_attribute("textContent").strip()
        self.assertIn("completed with some failures", status_text)
        self._assert_no_js_errors()

    def test_batch_completion_all_successful(self):
        """Test batch completion where all operations succeed"""
        batch_operation = BatchUpgradeOperation.objects.create(
            build=self.build2, status="in-progress"
        )
        UpgradeOperation.objects.create(
            device=self.device1,
            image=self.image2,
            batch=batch_operation,
            status="success",
            progress=100,
        )
        UpgradeOperation.objects.create(
            device=self.device2,
            image=self.image2,
            batch=batch_operation,
            status="success",
            progress=100,
        )
        self._prepare_batch(batch_operation)
        WebDriverWait(self.web_driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".batch-main-progress"))
        )
        publisher = BatchUpgradeProgressPublisher(batch_operation.pk)
        publisher.publish_batch_status(status="success", total=2, completed=2)
        WebDriverWait(self.web_driver, 10).until(
            EC.visibility_of_element_located(
                (
                    By.CSS_SELECTOR,
                    ".batch-main-progress .upgrade-progress-fill.completed-successfully",
                )
            )
        )
        progress_text = self.find_element(
            By.CSS_SELECTOR, ".batch-main-progress .upgrade-progress-text"
        ).text
        self.assertEqual(progress_text, "100%")
        status_field = self.find_element(By.CSS_SELECTOR, ".field-status .readonly")
        status_text = status_field.get_attribute("textContent").strip()
        self.assertIn("completed successfully", status_text)
        self._assert_no_js_errors()

    def test_dynamic_operation_addition_to_batch(self):
        """Test dynamic addition of new operations to batch upgrade view"""
        batch_operation = BatchUpgradeOperation.objects.create(
            build=self.build2, status="in-progress"
        )
        UpgradeOperation.objects.create(
            device=self.device1,
            image=self.image2,
            batch=batch_operation,
            status="in-progress",
            progress=50,
        )
        self._prepare_batch(batch_operation)
        initial_rows = WebDriverWait(self.web_driver, 10).until(
            EC.presence_of_all_elements_located(
                (By.CSS_SELECTOR, "#result_list tbody tr")
            )
        )
        self.assertEqual(len(initial_rows), 1)
        publisher = BatchUpgradeProgressPublisher(batch_operation.pk)
        operation2 = UpgradeOperation.objects.create(
            device=self.device2,
            image=self.image2,
            batch=batch_operation,
            status="in-progress",
            progress=0,
        )
        device_info_2 = {
            "device_id": self.device2.pk,
            "device_name": self.device2.name,
            "image_name": str(self.image2),
        }
        publisher.publish_operation_progress(
            str(operation2.pk), "in-progress", 0, operation2.modified, device_info_2
        )
        # Wait for websocket message to propagate and add new row
        WebDriverWait(self.web_driver, 10).until(
            lambda driver: self._check_row_count(2)
        )
        device_links = self.find_elements(By.CSS_SELECTOR, "#result_list .device-link")
        device_names = [link.text for link in device_links]
        self.assertIn(self.device2.name, device_names)
        status_containers = self.find_elements(
            By.CSS_SELECTOR, "#result_list .status-cell .upgrade-status-container"
        )
        self.assertEqual(len(status_containers), 2)
        self._assert_no_js_errors()
