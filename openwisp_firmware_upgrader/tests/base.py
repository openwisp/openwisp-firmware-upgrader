import os

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile

from openwisp_controller.connection.models import Credentials
from openwisp_controller.connection.tests.base import CreateConnectionsMixin

from ..models import Build, Category, DeviceFirmware, FirmwareImage


class TestUpgraderMixin(CreateConnectionsMixin):
    FAKE_IMAGE_PATH = os.path.join(settings.MEDIA_ROOT, 'fake-img.bin')
    TPLINK_4300_IMAGE = 'ar71xx-generic-tl-wdr4300-v1-squashfs-sysupgrade.bin'
    TPLINK_4300_IL_IMAGE = 'ar71xx-generic-tl-wdr4300-v1-il-squashfs-sysupgrade.bin'

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
        opts = dict(type=self.TPLINK_4300_IMAGE)
        opts.update(kwargs)
        if 'build' not in opts:
            opts['build'] = self._create_build()
        if 'file' not in opts:
            opts['file'] = self._get_simpleuploadedfile()
        fw = FirmwareImage(**opts)
        fw.full_clean()
        fw.save()
        return fw

    def _get_simpleuploadedfile(self):
        with open(self.FAKE_IMAGE_PATH, 'rb') as f:
            image = f.read()
        return SimpleUploadedFile(name='uploaded-fake-image.bin',
                                  content=image,
                                  content_type='text/plain')

    def _create_device_firmware(self, upgrade=False, device_connection=True, **kwargs):
        opts = dict()
        opts.update(kwargs)
        if 'image' not in opts:
            opts['image'] = self._create_firmware_image()
        if 'device' not in opts:
            opts['device'] = self._create_device(organization=opts['image'].build.organization)
            self._create_config(device=opts['device'])
        if device_connection:
            self._create_device_connection(device=opts['device'])
        device_fw = DeviceFirmware(**opts)
        device_fw.full_clean()
        device_fw.save(upgrade=upgrade)
        return device_fw

    def _create_upgrade_env(self, device_firmware=True):
        org = self._create_org()
        category = self._create_category(organization=org)
        build1 = self._create_build(category=category, version='0.1')
        image1a = self._create_firmware_image(build=build1, type=self.TPLINK_4300_IMAGE)
        image1b = self._create_firmware_image(build=build1, type=self.TPLINK_4300_IL_IMAGE)
        # create devices
        d1 = self._create_device(name='device1', organization=org,
                                 mac_address='00:22:bb:33:cc:44',
                                 model=image1a.boards[0])
        d2 = self._create_device(name='device2', organization=org,
                                 mac_address='00:11:bb:22:cc:33',
                                 model=image1b.boards[0])
        ssh_credentials = self._create_credentials(organization=None)
        self._create_config(device=d1)
        self._create_config(device=d2)
        self._create_device_connection(device=d1, credentials=ssh_credentials)
        self._create_device_connection(device=d2, credentials=ssh_credentials)
        # create device firmware (optional)
        if device_firmware:
            self._create_device_firmware(device=d1, image=image1a, device_connection=False)
            self._create_device_firmware(device=d2, image=image1b, device_connection=False)
        # create a new firmware build
        build2 = self._create_build(category=category, version='0.2')
        image2a = self._create_firmware_image(build=build2, type=self.TPLINK_4300_IMAGE)
        image2b = self._create_firmware_image(build=build2, type=self.TPLINK_4300_IL_IMAGE)
        data = {
            'build2': build2,
            'd1': d1,
            'd2': d2,
            'image1a': image1a,
            'image1b': image1b,
            'image2a': image2a,
            'image2b': image2b
        }
        return data

    def _create_firmwareless_device(self, organization):
        d = self._create_device(name='firmwareless',
                                mac_address='01:12:23:44:55:66',
                                organization=organization)
        self._create_config(device=d)
        self._create_device_connection(device=d,
                                       credentials=Credentials.objects.first())
        return d
