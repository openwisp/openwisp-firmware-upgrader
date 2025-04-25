import os
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase, TransactionTestCase
from swapper import load_model

from ..tasks import delete_firmware_files
from .base import TestUpgraderMixin

Build = load_model('firmware_upgrader', 'Build')
Category = load_model('firmware_upgrader', 'Category')
FirmwareImage = load_model('firmware_upgrader', 'FirmwareImage')
Organization = load_model('openwisp_users', 'Organization')


class TestSignals(TestUpgraderMixin, TestCase):
    def setUp(self):
        # Ensure PRIVATE_STORAGE_ROOT exists
        os.makedirs(settings.PRIVATE_STORAGE_ROOT, exist_ok=True)
        self._create_test_files()

    def tearDown(self):
        self._remove_test_files()
        super().tearDown()

    def _create_test_files(self):
        os.makedirs(settings.PRIVATE_STORAGE_ROOT, exist_ok=True)
        with open(self.FAKE_IMAGE_PATH, 'wb') as f:
            f.write(b'fake firmware image file')
        with open(self.FAKE_IMAGE_PATH2, 'wb') as f:
            f.write(b'fake firmware image file 2')

    def _remove_test_files(self):
        for path in [self.FAKE_IMAGE_PATH, self.FAKE_IMAGE_PATH2]:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
        try:
            os.rmdir(settings.PRIVATE_STORAGE_ROOT)
        except (FileNotFoundError, OSError):
            pass

    def test_build_delete_files(self):
        build = self._create_build()
        fw = self._create_firmware_image(build=build)
        file_path = fw.file.path
        self.assertTrue(os.path.exists(file_path))

        with patch(
            'openwisp_firmware_upgrader.tasks.delete_firmware_files.delay'
        ) as mock:
            build.delete()
            mock.assert_called_once()
            file_paths = mock.call_args[0][0]
            self.assertEqual(len(file_paths), 1)
            self.assertEqual(file_paths[0], fw.file.name)

    def test_category_delete_files(self):
        category = self._create_category()
        build1 = self._create_build(category=category)
        build2 = self._create_build(category=category)
        fw1 = self._create_firmware_image(build=build1)
        fw2 = self._create_firmware_image(build=build2)

        with patch(
            'openwisp_firmware_upgrader.tasks.delete_firmware_files.delay'
        ) as mock:
            category.delete()
            mock.assert_called_once()
            file_paths = mock.call_args[0][0]
            self.assertEqual(len(file_paths), 2)
            self.assertIn(fw1.file.name, file_paths)
            self.assertIn(fw2.file.name, file_paths)

    def test_organization_delete_files(self):
        org = self._get_org()
        category1 = self._create_category(organization=org)
        category2 = self._create_category(organization=org)
        build1 = self._create_build(category=category1)
        build2 = self._create_build(category=category2)
        fw1 = self._create_firmware_image(build=build1)
        fw2 = self._create_firmware_image(build=build2)

        with patch(
            'openwisp_firmware_upgrader.tasks.delete_firmware_files.delay'
        ) as mock:
            org.delete()
            mock.assert_called_once()
            file_paths = mock.call_args[0][0]
            self.assertEqual(len(file_paths), 2)
            self.assertIn(fw1.file.name, file_paths)
            self.assertIn(fw2.file.name, file_paths)


class TestDeleteFirmwareFilesTask(TestUpgraderMixin, TransactionTestCase):
    def setUp(self):
        # Ensure PRIVATE_STORAGE_ROOT exists
        os.makedirs(settings.PRIVATE_STORAGE_ROOT, exist_ok=True)
        self._create_test_files()

    def tearDown(self):
        self._remove_test_files()
        super().tearDown()

    def _create_test_files(self):
        with open(self.FAKE_IMAGE_PATH, 'wb') as f:
            f.write(b'fake firmware image file')
        with open(self.FAKE_IMAGE_PATH2, 'wb') as f:
            f.write(b'fake firmware image file 2')

    def _remove_test_files(self):
        for path in [self.FAKE_IMAGE_PATH, self.FAKE_IMAGE_PATH2]:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
        try:
            os.rmdir(settings.PRIVATE_STORAGE_ROOT)
        except (FileNotFoundError, OSError):
            pass

    def test_delete_firmware_files(self):
        build = self._create_build()
        fw = self._create_firmware_image(build=build)
        file_path = fw.file.path
        self.assertTrue(os.path.exists(file_path))

        # Create a list of file paths to delete
        file_paths = [fw.file.name]

        # Call the task directly
        delete_firmware_files(file_paths)

        # Check if the file has been deleted
        self.assertFalse(os.path.exists(file_path))

        # Check if the directory has been deleted
        dir_path = os.path.dirname(file_path)
        self.assertFalse(os.path.exists(dir_path))
