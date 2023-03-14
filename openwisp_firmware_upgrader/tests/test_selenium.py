from unittest.mock import patch

import swapper
from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.management import call_command
from django.urls.base import reverse
from reversion.models import Version
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, UnexpectedAlertPresentException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

from openwisp_controller.tests.utils import SeleniumTestMixin
from openwisp_firmware_upgrader.hardware import REVERSE_FIRMWARE_IMAGE_MAP
from openwisp_firmware_upgrader.tests.base import TestUpgraderMixin
from openwisp_utils.tests import capture_any_output

from ..swapper import load_model

Device = swapper.load_model('config', 'Device')
DeviceConnection = swapper.load_model('connection', 'DeviceConnection')
UpgradeOperation = load_model('UpgradeOperation')
DeviceFirmware = load_model('DeviceFirmware')
BatchUpgradeOperation = load_model('BatchUpgradeOperation')


class TestDeviceAdmin(TestUpgraderMixin, SeleniumTestMixin, StaticLiveServerTestCase):
    config_app_label = 'config'
    firmware_app_label = 'firmware_upgrader'
    admin_username = 'admin'
    admin_password = 'password'
    os = 'OpenWrt 19.07-SNAPSHOT r11061-6ffd4d8a4d'
    image_type = REVERSE_FIRMWARE_IMAGE_MAP['YunCore XD3200']

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        chrome_options = webdriver.ChromeOptions()
        if getattr(settings, 'SELENIUM_HEADLESS', True):
            chrome_options.add_argument('--headless')
        chrome_options.add_argument('--window-size=1366,768')
        chrome_options.add_argument('--ignore-certificate-errors')
        chrome_options.add_argument('--remote-debugging-port=9222')
        capabilities = DesiredCapabilities.CHROME
        capabilities['goog:loggingPrefs'] = {'browser': 'ALL'}
        cls.web_driver = webdriver.Chrome(
            options=chrome_options, desired_capabilities=capabilities
        )

    @classmethod
    def tearDownClass(cls):
        cls.web_driver.quit()
        super().tearDownClass()

    def setUp(self):
        self.admin = self._create_admin(
            username=self.admin_username, password=self.admin_password
        )

    def tearDown(self):
        # Accept unsaved changes alert to allow other tests to run
        try:
            self.web_driver.refresh()
        except UnexpectedAlertPresentException:
            self.web_driver.switch_to_alert().accept()
        else:
            try:
                WebDriverWait(self.web_driver, 1).until(EC.alert_is_present())
            except TimeoutException:
                pass
            else:
                self.web_driver.switch_to_alert().accept()
        self.web_driver.refresh()
        WebDriverWait(self.web_driver, 2).until(
            EC.visibility_of_element_located((By.XPATH, '//*[@id="site-name"]'))
        )

    @capture_any_output()
    def test_restoring_deleted_device(self):
        org = self._get_org()
        category = self._get_category(organization=org)
        build = self._create_build(category=category, version='0.1', os=self.os)
        image = self._create_firmware_image(build=build, type=self.image_type)
        self._create_credentials(auto_add=True, organization=org)
        device = self._create_device(
            os=self.os, model=image.boards[0], organization=org
        )
        self._create_config(device=device)
        self.assertEqual(Device.objects.count(), 1)
        self.assertEqual(DeviceConnection.objects.count(), 1)
        self.assertEqual(DeviceFirmware.objects.count(), 1)

        call_command('createinitialrevisions')

        self.login()
        # Delete the device
        self.open(
            reverse(f'admin:{self.config_app_label}_device_delete', args=[device.id])
        )
        self.web_driver.find_element_by_xpath(
            '//*[@id="content"]/form/div/input[2]'
        ).click()
        self.assertEqual(Device.objects.count(), 0)
        self.assertEqual(DeviceConnection.objects.count(), 0)
        self.assertEqual(DeviceFirmware.objects.count(), 0)

        version_obj = Version.objects.get_deleted(model=Device).first()

        # Restore deleted device
        self.open(
            reverse(
                f'admin:{self.config_app_label}_device_recover', args=[version_obj.id]
            )
        )
        self.web_driver.find_element_by_xpath(
            '//*[@id="device_form"]/div/div[1]/input[1]'
        ).click()
        try:
            WebDriverWait(self.web_driver, 5).until(
                EC.url_to_be(f'{self.live_server_url}/admin/config/device/')
            )
        except TimeoutException:
            self.fail('Deleted device was not restored')

        self.assertEqual(Device.objects.count(), 1)
        self.assertEqual(DeviceConnection.objects.count(), 1)
        self.assertEqual(DeviceFirmware.objects.count(), 1)

    @capture_any_output()
    @patch(
        'openwisp_firmware_upgrader.upgraders.openwrt.OpenWrt.upgrade',
        return_value=True,
    )
    @patch(
        'openwisp_controller.connection.models.DeviceConnection.connect',
        return_value=True,
    )
    def test_device_firmware_upgrade_options(self, *args):
        def save_device():
            self.web_driver.find_element_by_xpath(
                '//*[@id="device_form"]/div/div[1]/input[3]'
            ).click()

        org = self._get_org()
        category = self._get_category(organization=org)
        build1 = self._create_build(category=category, version='0.1', os=self.os)
        build2 = self._create_build(
            category=category, version='0.2', os='OpenWrt 21.03'
        )
        self._create_firmware_image(build=build1, type=self.image_type)
        image = self._create_firmware_image(build=build2, type=self.image_type)
        self._create_credentials(auto_add=True, organization=org)
        device = self._create_device(
            os=self.os, model=image.boards[0], organization=org
        )
        self._create_config(device=device)
        self.login()
        self.open(
            '{}#devicefirmware-group'.format(
                reverse(
                    f'admin:{self.config_app_label}_device_change', args=[device.id]
                )
            )
        )
        # JSONSchema Editor should not be rendered without a change in the image field
        WebDriverWait(self.web_driver, 1).until(
            EC.invisibility_of_element_located(
                (By.CSS_SELECTOR, '#devicefirmware-group .jsoneditor-wrapper')
            )
        )
        image_select = Select(
            self.web_driver.find_element_by_id('id_devicefirmware-0-image')
        )
        image_select.select_by_index(1)
        # JSONSchema configuration editor should not be rendered
        WebDriverWait(self.web_driver, 1).until(
            EC.invisibility_of_element_located(
                (
                    By.XPATH,
                    '//*[@id="id_devicefirmware-0-upgrade_options_jsoneditor"]/div/h3/span[4]/input',
                )
            )
        )
        # Enable '-c' option
        self.web_driver.find_element_by_xpath(
            '//*[@id="id_devicefirmware-0-upgrade_options_jsoneditor"]'
            '/div/div[2]/div/div/div[1]/div/div[1]/label/input'
        ).click()
        # Enable '-F' option
        self.web_driver.find_element_by_xpath(
            '//*[@id="id_devicefirmware-0-upgrade_options_jsoneditor"]'
            '/div/div[2]/div/div/div[7]/div/div[1]/label/input'
        ).click()
        save_device()

        # Delete DeviceFirmware
        self.web_driver.find_element_by_id('id_devicefirmware-0-DELETE').click()
        save_device()

        # When adding firmware to the device for the first time,
        # JSONSchema editor should be rendered only when the image
        # is selected
        self.web_driver.find_element_by_xpath(
            '//*[@id="devicefirmware-group"]/fieldset/div[2]/a'
        ).click()
        # JSONSchema Editor should not be rendered without a change in the image field
        WebDriverWait(self.web_driver, 1).until(
            EC.invisibility_of_element_located(
                (By.CSS_SELECTOR, '#devicefirmware-group .jsoneditor-wrapper')
            )
        )
        image_select = Select(
            self.web_driver.find_element_by_id('id_devicefirmware-0-image')
        )
        image_select.select_by_index(1)
        try:
            WebDriverWait(self.web_driver, 1).until(
                EC.visibility_of_element_located(
                    (By.CSS_SELECTOR, '#devicefirmware-group .jsoneditor-wrapper')
                )
            )
        except TimeoutError:
            self.fail('JSONSchema editor not shown after changing firmware image')
        save_device()

    @capture_any_output()
    @patch(
        'openwisp_firmware_upgrader.upgraders.openwrt.OpenWrt.upgrade',
        return_value=True,
    )
    @patch(
        'openwisp_controller.connection.models.DeviceConnection.connect',
        return_value=True,
    )
    def test_batch_upgrade_upgrade_options(self, *args):
        org = self._get_org()
        category = self._get_category(organization=org)
        build1 = self._create_build(category=category, version='0.1', os=self.os)
        build2 = self._create_build(
            category=category, version='0.2', os='OpenWrt 21.03'
        )
        self._create_firmware_image(build=build1, type=self.image_type)
        image = self._create_firmware_image(build=build2, type=self.image_type)
        self._create_credentials(auto_add=True, organization=org)
        device = self._create_device(
            os=self.os, model=image.boards[0], organization=org
        )
        self._create_config(device=device)
        self.login()
        self.open(
            reverse(f'admin:{self.firmware_app_label}_build_change', args=[build2.id])
        )
        # Launch mass upgrade operation
        self.web_driver.find_element_by_css_selector(
            '.title-wrapper .object-tools form button[type="submit"]'
        ).click()

        # Ensure JSONSchema form is rendered
        try:
            WebDriverWait(self.web_driver, 1).until(
                EC.visibility_of_element_located(
                    (By.CSS_SELECTOR, '.jsoneditor-wrapper')
                )
            )
        except TimeoutError:
            self.fail('JSONSchema editor not shown after changing firmware image')
        # JSONSchema configuration editor should not be rendered
        WebDriverWait(self.web_driver, 1).until(
            EC.invisibility_of_element_located(
                (
                    By.XPATH,
                    '//*[@id="id_devicefirmware-0-upgrade_options_jsoneditor"]/div/h3/span[4]/input',
                )
            )
        )
        # Enable -o flag
        self.web_driver.find_element_by_xpath(
            '//*[@id="id_upgrade_options_jsoneditor"]/div/div[2]/div/div/div[2]/div/div[1]/label/input'
        ).click()
        # Enable -u flag
        self.web_driver.find_element_by_xpath(
            '//*[@id="id_upgrade_options_jsoneditor"]/div/div[2]/div/div/div[3]/div/div[1]/label/input'
        ).click()
        # Upgrade all devices
        self.web_driver.find_element_by_css_selector(
            'input[name="upgrade_all"]'
        ).click()
        self.assertEqual(
            BatchUpgradeOperation.objects.filter(
                upgrade_options={
                    'c': False,
                    'o': True,
                    'u': True,
                    'n': False,
                    'p': False,
                    'k': False,
                    'F': False,
                }
            ).count(),
            1,
        )
        self.assertEqual(
            UpgradeOperation.objects.filter(
                upgrade_options={
                    'c': False,
                    'o': True,
                    'u': True,
                    'n': False,
                    'p': False,
                    'k': False,
                    'F': False,
                }
            ).count(),
            1,
        )
