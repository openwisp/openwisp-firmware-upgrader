import os

import mock
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django_netjsonconfig.tests import CreateConfigMixin

from openwisp_controller.config.models import Device
from openwisp_users.tests.utils import TestOrganizationMixin

from ..models import Build, Category, DeviceFirmware, FirmwareImage, UpgradeOperation


class TestUpgraderMixin(CreateConfigMixin, TestOrganizationMixin):
    device_model = Device
    _fake_image_path = os.path.join(settings.MEDIA_ROOT, 'fake-img.bin')

    def tearDown(self):
        for fw in FirmwareImage.objects.all():
            fw.delete()

    def _create_category(self, **kwargs):
        opts = dict(name='Test Category')
        opts.update(kwargs)
        if 'organization' not in opts:
            opts['organization'] = self._create_org()
        c = Category(**opts)
        c.full_clean()
        c.save()
        return c

    def _create_build(self, **kwargs):
        opts = dict(version='0.1')
        opts.update(kwargs)
        if 'category' not in opts:
            opts['category'] = self._create_category()
        if 'organization' not in opts:
            opts['organization'] = opts['category'].organization
        b = Build(**opts)
        b.full_clean()
        b.save()
        return b

    def _create_firmware_image(self, **kwargs):
        opts = dict(models='TP-Link TL-WDR4300 v1')
        opts.update(kwargs)
        if 'build' not in opts:
            opts['build'] = self._create_build()
        if 'organization' not in opts:
            opts['organization'] = opts['build'].organization
        if 'file' not in opts:
            opts['file'] = self._get_simpleuploadedfile()
        fw = FirmwareImage(**opts)
        fw.full_clean()
        fw.save()
        return fw

    def _get_simpleuploadedfile(self):
        with open(self._fake_image_path, 'rb') as f:
            image = f.read()
        return SimpleUploadedFile(name='uploaded-fake-image.bin',
                                  content=image,
                                  content_type='text/plain')

    def _create_device_firmware(self, **kwargs):
        opts = dict()
        opts.update(kwargs)
        if 'image' not in opts:
            opts['image'] = self._create_firmware_image()
        if 'device' not in opts:
            opts['device'] = self._create_device(organization=opts['image'].organization)
        device_fw = DeviceFirmware(**opts)
        device_fw.full_clean()
        device_fw.save()
        return device_fw


class TestModels(TestUpgraderMixin, TestCase):
    def test_category_str(self):
        c = Category(name='WiFi Hotspot')
        self.assertEqual(str(c), c.name)

    def test_build_str(self):
        c = self._create_category()
        b = Build(category=c, version='0.1')
        self.assertIn(c.name, str(b))
        self.assertIn(b.version, str(b))

    def test_build_str_no_category(self):
        b = Build()
        self.assertIsNotNone(str(b))

    def test_fw_str(self):
        fw = self._create_firmware_image()
        self.assertIn(str(fw.build), str(fw))
        self.assertIn(fw.file.name, str(fw))

    def test_fw_str_new(self):
        fw = FirmwareImage()
        self.assertIsNotNone(str(fw))

    @mock.patch('openwisp_firmware_upgrader.models.UpgradeOperation.upgrade', return_value=None)
    def test_device_fw_image_changed(self, *args):
        device_fw = DeviceFirmware()
        self.assertIsNone(device_fw._old_image)
        # save
        device_fw = self._create_device_firmware()
        self.assertEqual(device_fw._old_image, device_fw.image)
        self.assertEqual(UpgradeOperation.objects.count(), 0)
        # init
        device_fw = DeviceFirmware.objects.first()
        self.assertEqual(device_fw._old_image, device_fw.image)
        # change
        build2 = self._create_build(category=device_fw.image.build.category,
                                    version='0.2',
                                    previous=device_fw.image.build)
        fw2 = self._create_firmware_image(build=build2, models=device_fw.image.models)
        old_image = device_fw.image
        device_fw.image = fw2
        self.assertNotEqual(device_fw._old_image, device_fw.image)
        self.assertEqual(device_fw._old_image, old_image)
        device_fw.full_clean()
        device_fw.save()
        self.assertEqual(UpgradeOperation.objects.count(), 1)
