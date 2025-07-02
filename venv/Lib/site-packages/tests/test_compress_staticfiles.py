import os
from unittest import mock
import tempfile
import json

from django.test import TestCase
from django.core.management import call_command
from django.conf import settings
from django.test import override_settings

from compress_staticfiles.storage import (
    MinifyFilesMixin, CompressStaticFilesStorage
)
from tests.settings import TEST_SETTINGS, TEST_ROOT


@override_settings(**TEST_SETTINGS)
class CompressStaticfilesStorage(TestCase):

    def setUp(self):
        self.compress_file_storage = CompressStaticFilesStorage()


    @mock.patch(
        'compress_staticfiles.storage.CompressStaticFilesStorage.log'
    )
    def test_manifest_was_updated_with_hashed_and_minified_versions(self, mock_log):
        TEMP_STATIC_ROOT = tempfile.TemporaryDirectory(
            dir=TEST_ROOT
        ) # this does *not* require manual cleanup
        settings.STATIC_ROOT = os.path.join(
            TEST_ROOT, TEMP_STATIC_ROOT.name
        )
        call_command(
            'collectstatic', interactive=False, verbosity=0,
        )
        manifest_file_fp = os.path.join(settings.STATIC_ROOT, 'staticfiles.json')
        with open(manifest_file_fp, 'r') as manifest_file:
            manifest_json = manifest_file.read()
            manifest_dict = json.loads(manifest_json)
            # Make sure the manifest gets updated correctly.
            assert manifest_dict['paths']['test/test.css'] == 'test/test.min.815f6efe5516.css'
            assert manifest_dict['paths']['test/test.js'] == 'test/test.min.7cf6ab9e3734.js'


    def test_included_filetypes(self):
        included_filetypes = self.compress_file_storage.included_filetypes

        # Make sure these filetypes are never processed
        assert '.jpg' not in included_filetypes
        assert '.jpeg' not in included_filetypes
        assert '.webp' not in included_filetypes
        assert '.png' not in included_filetypes
        assert '.tiff' not in included_filetypes
        assert '.bmp' not in included_filetypes
        assert '.gif' not in included_filetypes
        assert '.woff' not in included_filetypes
        assert '.gz' not in included_filetypes
        assert '.br' not in included_filetypes
        assert '.zip' not in included_filetypes
        assert '.rar' not in included_filetypes

        # Check that, at least, just css and js are included
        assert '.css' in included_filetypes
        assert '.js' in included_filetypes


    def test_default_settings(self):
        assert settings.MINIFY_STATIC is True
        assert settings.BROTLI_STATIC_COMPRESSION is True
        assert settings.GZIP_STATIC_COMPRESSION is True
