from unittest.mock import MagicMock, patch

from django.test import TestCase

from .. import settings as app_settings
from ..swapper import load_model
from ..utils import delete_file_and_cleanup, get_upgrader_class_from_device_connection
from .base import TestUpgraderMixin

FirmwareImage = load_model("FirmwareImage")


class TestUtils(TestUpgraderMixin, TestCase):
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

    @patch("openwisp_firmware_upgrader.utils.logger")
    def test_delete_file_and_cleanup_success(self, mock_logger):
        """Test successful file deletion with empty directory cleanup"""
        mock_storage = MagicMock()
        mock_storage.listdir.return_value = ([], [])  # Empty directory
        result = delete_file_and_cleanup(mock_storage, "build/123/firmware.bin")
        self.assertTrue(result)
        mock_storage.delete.assert_any_call("build/123/firmware.bin")
        mock_storage.delete.assert_any_call("build/123")
        # Verify log messages
        mock_logger.info.assert_any_call(
            "Deleted firmware file: %s", "build/123/firmware.bin"
        )
        mock_logger.info.assert_any_call("Deleted empty directory: %s", "build/123")
        self.assertEqual(mock_storage.delete.call_count, 2)

    @patch("openwisp_firmware_upgrader.utils.logger")
    def test_delete_file_and_cleanup_non_empty_directory(self, mock_logger):
        """Test file deletion when directory is not empty"""
        mock_storage = MagicMock()
        mock_storage.listdir.return_value = (["subdir"], ["other_file.bin"])
        result = delete_file_and_cleanup(mock_storage, "build/123/firmware.bin")
        self.assertTrue(result)
        mock_storage.delete.assert_called_once_with("build/123/firmware.bin")
        # Verify log messages
        mock_logger.info.assert_called_once_with(
            "Deleted firmware file: %s", "build/123/firmware.bin"
        )
        mock_logger.debug.assert_called_once_with(
            "Directory %s is not empty, skipping deletion", "build/123"
        )

    @patch("openwisp_firmware_upgrader.utils.logger")
    def test_delete_file_and_cleanup_file_deletion_failure(self, mock_logger):
        """Test when file deletion fails"""
        mock_storage = MagicMock()
        mock_storage.delete.side_effect = Exception("Storage error")
        result = delete_file_and_cleanup(mock_storage, "build/123/firmware.bin")
        self.assertFalse(result)
        mock_storage.delete.assert_called_once_with("build/123/firmware.bin")
        # Verify error log message
        mock_logger.error.assert_called_once_with(
            "Error deleting firmware file %s: %s",
            "build/123/firmware.bin",
            "Storage error",
        )
        mock_logger.info.assert_not_called()

    @patch("openwisp_firmware_upgrader.utils.logger")
    def test_delete_file_and_cleanup_directory_listing_failure(self, mock_logger):
        """Test when directory listing fails"""
        mock_storage = MagicMock()
        mock_storage.listdir.side_effect = Exception("Directory access error")
        result = delete_file_and_cleanup(mock_storage, "build/123/firmware.bin")

        self.assertTrue(result)  # File deletion succeeded, directory cleanup failed
        mock_storage.delete.assert_called_once_with("build/123/firmware.bin")
        # Verify log messages
        mock_logger.info.assert_called_once_with(
            "Deleted firmware file: %s", "build/123/firmware.bin"
        )
        mock_logger.warning.assert_called_once_with(
            "Could not delete directory %s: %s", "build/123", "Directory access error"
        )

    @patch("openwisp_firmware_upgrader.utils.logger")
    def test_delete_file_and_cleanup_directory_not_found(self, mock_logger):
        """Test when directory doesn't exist (FileNotFoundError)"""
        mock_storage = MagicMock()
        mock_storage.listdir.side_effect = FileNotFoundError("Directory not found")
        result = delete_file_and_cleanup(mock_storage, "build/123/firmware.bin")
        self.assertTrue(result)  # File deletion succeeded
        mock_storage.delete.assert_called_once_with("build/123/firmware.bin")
        # Verify log messages - should be debug, not warning
        mock_logger.info.assert_called_once_with(
            "Deleted firmware file: %s", "build/123/firmware.bin"
        )
        mock_logger.debug.assert_called_once_with(
            "Directory %s already removed", "build/123"
        )
        mock_logger.warning.assert_not_called()

    @patch("openwisp_firmware_upgrader.utils.logger")
    def test_delete_file_and_cleanup_directory_deletion_failure(self, mock_logger):
        """Test when directory deletion fails"""
        mock_storage = MagicMock()
        mock_storage.listdir.return_value = ([], [])  # Empty directory
        mock_storage.delete.side_effect = [None, Exception("Directory deletion error")]
        result = delete_file_and_cleanup(mock_storage, "build/123/firmware.bin")
        self.assertTrue(result)  # File deletion succeeded, directory cleanup failed
        # Verify log messages
        mock_logger.info.assert_called_once_with(
            "Deleted firmware file: %s", "build/123/firmware.bin"
        )
        mock_logger.warning.assert_called_once_with(
            "Could not delete directory %s: %s", "build/123", "Directory deletion error"
        )

    @patch("openwisp_firmware_upgrader.utils.logger")
    def test_delete_file_and_cleanup_root_directory(self, mock_logger):
        """Test file deletion when parent is root directory"""
        mock_storage = MagicMock()
        result = delete_file_and_cleanup(mock_storage, "firmware.bin")
        self.assertTrue(result)
        mock_storage.delete.assert_called_once_with("firmware.bin")
        mock_storage.listdir.assert_not_called()  # Should skip directory cleanup
        # Verify log message
        mock_logger.info.assert_called_once_with(
            "Deleted firmware file: %s", "firmware.bin"
        )
