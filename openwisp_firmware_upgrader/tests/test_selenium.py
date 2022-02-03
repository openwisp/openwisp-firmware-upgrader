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
from selenium.webdriver.support.ui import WebDriverWait

from openwisp_controller.tests.utils import SeleniumTestMixin
from openwisp_firmware_upgrader.hardware import REVERSE_FIRMWARE_IMAGE_MAP
from openwisp_firmware_upgrader.tests.base import TestUpgraderMixin
from openwisp_utils.tests import capture_any_output

from ..swapper import load_model

Device = swapper.load_model('config', 'Device')
DeviceConnection = swapper.load_model('connection', 'DeviceConnection')
UpgradeOperation = load_model('UpgradeOperation')
DeviceFirmware = load_model('DeviceFirmware')


class TestDeviceAdmin(TestUpgraderMixin, SeleniumTestMixin, StaticLiveServerTestCase):
    config_app_label = 'config'
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
