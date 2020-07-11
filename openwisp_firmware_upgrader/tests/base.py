import os
from unittest import mock

import swapper
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile

from openwisp_controller.connection.tests.utils import CreateConnectionsMixin

from ..swapper import load_model

Build = load_model('Build')
Category = load_model('Category')
FirmwareImage = load_model('FirmwareImage')
DeviceFirmware = load_model('DeviceFirmware')
DeviceFirmware = load_model('DeviceFirmware')
Credentials = swapper.load_model('connection', 'Credentials')


class TestUpgraderMixin(CreateConnectionsMixin):
    FAKE_IMAGE_PATH = os.path.join(settings.PRIVATE_STORAGE_ROOT, 'fake-img.bin')
    FAKE_IMAGE_PATH2 = os.path.join(settings.PRIVATE_STORAGE_ROOT, 'fake-img2.bin')
    TPLINK_4300_IMAGE = 'ar71xx-generic-tl-wdr4300-v1-squashfs-sysupgrade.bin'
    TPLINK_4300_IL_IMAGE = 'ar71xx-generic-tl-wdr4300-v1-il-squashfs-sysupgrade.bin'

    def tearDown(self):
        for fw in FirmwareImage.objects.all():
            fw.delete()

    def _get_build(self, version="0.1", **kwargs):
        opts = {"version": version}
        opts.update(kwargs)
        try:
            return Build.objects.get(**opts)
        except Build.DoesNotExist:
            return self._create_build(**opts)

    def _get_category(self, cat_name="Test Category", **kwargs):
        opts = {"name": cat_name}
        opts.update(kwargs)
        try:
            return Category.objects.get(**opts)
        except Category.DoesNotExist:
            return self._create_category(**opts)

    def _create_category(self, **kwargs):
        opts = dict(name='Test Category')
        opts.update(kwargs)
        if 'organization' not in opts:
            opts['organization'] = self._get_org()
        c = Category(**opts)
        c.full_clean()
        c.save()
        return c

    def _create_build(self, **kwargs):
        opts = dict(version='0.1')
        opts.update(kwargs)
        category_opts = {}
        if 'organization' in opts:
            category_opts = {'organization': opts.pop('organization')}
        if 'category' not in opts:
            opts['category'] = self._get_category(**category_opts)
        b = Build(**opts)
        b.full_clean()
        b.save()
        return b

    def _create_firmware_image(self, **kwargs):
        opts = dict(type=self.TPLINK_4300_IMAGE)
        opts.update(kwargs)
        build_opts = {}
        if 'organization' in opts:
            build_opts['organization'] = opts.pop('organization')
        if 'build' not in opts:
            opts['build'] = self._get_build(**build_opts)
        if 'file' not in opts:
            opts['file'] = self._get_simpleuploadedfile()
        fw = FirmwareImage(**opts)
        fw.full_clean()
        fw.save()
        return fw

    def _get_simpleuploadedfile(self, filename=None):
        if not filename:
            filename = self.FAKE_IMAGE_PATH
        with open(filename, 'rb') as f:
            image = f.read()
        return SimpleUploadedFile(
            name=f'openwrt-{self.TPLINK_4300_IMAGE}',
            content=image,
            content_type='application/octet-stream',
        )

    def _create_device_firmware(self, upgrade=False, device_connection=True, **kwargs):
        opts = dict()
        opts.update(kwargs)
        if 'image' not in opts:
            opts['image'] = self._create_firmware_image()
        if 'device' not in opts:
            org = opts['image'].build.category.organization
            opts['device'] = self._create_device(organization=org)
            self._create_config(device=opts['device'])
        if device_connection:
            self._create_device_connection(device=opts['device'])
        device_fw = DeviceFirmware(**opts)
        device_fw.full_clean()
        device_fw.save(upgrade=upgrade)
        return device_fw

    def _create_upgrade_env(self, device_firmware=True, **kwargs):
        org = kwargs.pop('organization', self._get_org())
        category = kwargs.pop('category', self._get_category(organization=org))
        build1 = self._create_build(category=category, version='0.1')
        image1a = self._create_firmware_image(build=build1, type=self.TPLINK_4300_IMAGE)
        image1b = self._create_firmware_image(
            build=build1, type=self.TPLINK_4300_IL_IMAGE
        )
        # create devices
        d1 = self._create_device(
            name='device1',
            organization=org,
            mac_address='00:22:bb:33:cc:44',
            model=image1a.boards[0],
        )
        d2 = self._create_device(
            name='device2',
            organization=org,
            mac_address='00:11:bb:22:cc:33',
            model=image1b.boards[0],
        )
        ssh_credentials = self._get_credentials(organization=None)
        self._create_config(device=d1)
        self._create_config(device=d2)
        self._create_device_connection(device=d1, credentials=ssh_credentials)
        self._create_device_connection(device=d2, credentials=ssh_credentials)
        # force create device firmware (optional)
        if device_firmware:
            self._create_device_firmware(
                device=d1, image=image1a, device_connection=False
            )
            self._create_device_firmware(
                device=d2, image=image1b, device_connection=False
            )
        # create a new firmware build
        build2 = self._create_build(category=category, version='0.2')
        image2a = self._create_firmware_image(build=build2, type=self.TPLINK_4300_IMAGE)
        image2b = self._create_firmware_image(
            build=build2, type=self.TPLINK_4300_IL_IMAGE
        )
        data = {
            'build1': build1,
            'build2': build2,
            'd1': d1,
            'd2': d2,
            'image1a': image1a,
            'image1b': image1b,
            'image2a': image2a,
            'image2b': image2b,
        }
        return data

    def _create_firmwareless_device(self, organization):
        d = self._create_device(
            name='firmwareless',
            mac_address='01:12:23:44:55:66',
            organization=organization,
        )
        self._create_config(device=d)
        self._create_device_connection(
            device=d, credentials=Credentials.objects.first()
        )
        return d

    def _create_device_with_connection(self, **kwargs):
        d1 = self._create_device(**kwargs)
        self._create_config(device=d1)
        self._create_device_connection(device=d1)
        return d1


def spy_mock(method, pre_action):
    magicmock = mock.MagicMock()

    def wrapper(*args, **kwargs):
        magicmock(*args, **kwargs)
        pre_action(*args, **kwargs)
        return method(*args, **kwargs)

    wrapper.mock = magicmock
    return wrapper
