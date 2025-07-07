import os

from django.conf import settings
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


class SeleniumTestMixin:
    """A base Mixin Class for Selenium Browser Tests.

    Provides common initialization logic and helper methods like login()
    and open().
    """

    admin_username = 'admin'
    admin_password = 'password'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        chrome_options = webdriver.ChromeOptions()
        chrome_options.page_load_strategy = 'eager'
        if getattr(settings, 'SELENIUM_HEADLESS', True):
            chrome_options.add_argument('--headless')
        CHROME_BIN = os.environ.get('CHROME_BIN', None)
        if CHROME_BIN:
            chrome_options.binary_location = CHROME_BIN
        chrome_options.add_argument('--window-size=1366,768')
        chrome_options.add_argument('--ignore-certificate-errors')
        # When running Selenium tests with the "--parallel" flag,
        # each TestCase class requires its own browser instance.
        # If the same "remote-debugging-port" is used for all
        # TestCase classes, it leads to failed test cases.
        # Therefore, it is necessary to utilize different remote
        # debugging ports for each TestCase. To accomplish this,
        # we can leverage the randomized live test server port to
        # generate a unique port for each browser instance.
        chrome_options.add_argument(
            f'--remote-debugging-port={cls.server_thread.port + 100}'
        )
        capabilities = DesiredCapabilities.CHROME
        capabilities['goog:loggingPrefs'] = {'browser': 'ALL'}
        chrome_options.set_capability('cloud:options', capabilities)
        cls.web_driver = webdriver.Chrome(
            options=chrome_options,
        )

    @classmethod
    def tearDownClass(cls):
        cls.web_driver.quit()
        super().tearDownClass()

    def open(self, url, driver=None):
        """Opens a URL.

        Input Arguments:

        - url: URL to open
        - driver: selenium driver (default: cls.base_driver).
        """
        if not driver:
            driver = self.web_driver
        driver.get(f'{self.live_server_url}{url}')
        WebDriverWait(self.web_driver, 2).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, '#main-content'))
        )

    def login(self, username=None, password=None, driver=None):
        """Log in to the admin dashboard.

        Input Arguments:

        - username: username to be used for login (default:
          cls.admin_username)
        - password: password to be used for login (default:
          cls.admin_password)
        - driver: selenium driver (default: cls.web_driver).
        """
        if not driver:
            driver = self.web_driver
        if not username:
            username = self.admin_username
        if not password:
            password = self.admin_password
        driver.get(f'{self.live_server_url}/admin/login/')
        if 'admin/login' in driver.current_url:
            driver.find_element(by=By.NAME, value='username').send_keys(username)
            driver.find_element(by=By.NAME, value='password').send_keys(password)
            driver.find_element(by=By.XPATH, value='//input[@type="submit"]').click()
