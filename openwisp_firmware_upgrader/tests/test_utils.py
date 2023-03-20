from unittest.mock import patch

from django.test import TestCase

from .. import settings as app_settings
from ..utils import get_upgrader_class_from_device_connection
from .base import TestUpgraderMixin


class TestUtils(TestUpgraderMixin, TestCase):
    @patch('logging.Logger.exception')
    def test_get_upgrader_class_from_device_connection(self, mocked_logger):
        device_conn = self._create_device_connection()

        with self.subTest('Test upgrader is not configured in "UPGRADERS_MAP"'):
            with patch.object(app_settings, 'UPGRADERS_MAP', {}):
                upgrader_class = get_upgrader_class_from_device_connection(device_conn)
                self.assertEqual(upgrader_class, None)
                mocked_logger.assert_called()

        mocked_logger.reset_mock()

        with self.subTest('Test upgrader is not configured in "UPGRADERS_MAP"'):
            with patch.object(
                app_settings,
                'UPGRADERS_MAP',
                {
                    device_conn.update_strategy: 'openwisp_firmware_upgrader.upgraders.invalid'
                },
            ):
                upgrader_class = get_upgrader_class_from_device_connection(device_conn)
                self.assertEqual(upgrader_class, None)
                mocked_logger.assert_called()
