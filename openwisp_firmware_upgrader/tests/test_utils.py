from datetime import datetime, timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase

from .. import settings as app_settings
from ..utils import get_upgrader_class_from_device_connection, reinterpret_in_timezone
from .base import TestUpgraderMixin


class TestUtils(TestUpgraderMixin, TestCase):
    def test_reinterpret_in_timezone(self):
        with self.subTest("valid wall-clock is localized to the timezone"):
            result = reinterpret_in_timezone(
                datetime(2026, 6, 15, 12, 0), "America/New_York"
            )
            self.assertEqual(result.utcoffset(), timedelta(hours=-4))

        with self.subTest("invalid timezone is rejected"):
            with self.assertRaises(ValidationError):
                reinterpret_in_timezone(datetime(2026, 6, 15, 12, 0), "Not/AZone")

        with self.subTest("nonexistent time (spring-forward gap) is rejected"):
            with self.assertRaises(ValidationError):
                reinterpret_in_timezone(datetime(2026, 3, 8, 2, 30), "America/New_York")

        with self.subTest("ambiguous time (fall-back fold) is rejected"):
            with self.assertRaises(ValidationError):
                reinterpret_in_timezone(
                    datetime(2026, 11, 1, 1, 30), "America/New_York"
                )

    @patch("logging.Logger.exception")
    def test_get_upgrader_class_from_device_connection(self, mocked_logger):
        device_conn = self._create_device_connection()

        with self.subTest('Test upgrader is not configured in "UPGRADERS_MAP"'):
            with patch.object(app_settings, "UPGRADERS_MAP", {}):
                upgrader_class = get_upgrader_class_from_device_connection(device_conn)
                self.assertEqual(upgrader_class, None)
                mocked_logger.assert_called()

        mocked_logger.reset_mock()

        with self.subTest('Test upgrader is not configured in "UPGRADERS_MAP"'):
            with patch.object(
                app_settings,
                "UPGRADERS_MAP",
                {
                    device_conn.update_strategy: "openwisp_firmware_upgrader.upgraders.invalid"
                },
            ):
                upgrader_class = get_upgrader_class_from_device_connection(device_conn)
                self.assertEqual(upgrader_class, None)
                mocked_logger.assert_called()
