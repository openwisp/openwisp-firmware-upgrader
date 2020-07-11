import io
from contextlib import redirect_stdout
from unittest import mock

import swapper
from celery.exceptions import Retry
from django.core.exceptions import ValidationError
from django.test import TestCase, TransactionTestCase

from openwisp_controller.config.models import Device

from .. import settings as app_settings
from ..hardware import FIRMWARE_IMAGE_MAP, REVERSE_FIRMWARE_IMAGE_MAP
from ..swapper import load_model
from ..tasks import upgrade_firmware
from .base import TestUpgraderMixin

Group = swapper.load_model('openwisp_users', 'Group')
BatchUpgradeOperation = load_model('BatchUpgradeOperation')
Build = load_model('Build')
Category = load_model('Category')
DeviceFirmware = load_model('DeviceFirmware')
FirmwareImage = load_model('FirmwareImage')
UpgradeOperation = load_model('UpgradeOperation')
DeviceConnection = swapper.load_model('connection', 'DeviceConnection')
Credentials = swapper.load_model('connection', 'Credentials')


class TestModels(TestUpgraderMixin, TestCase):
    app_label = 'openwisp_firmware_upgrader'
    os = 'OpenWrt 19.07-SNAPSHOT r11061-6ffd4d8a4d'
    image_type = REVERSE_FIRMWARE_IMAGE_MAP['YunCore XD3200']

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

    def test_build_clean(self):
        org = self._get_org()
        cat1 = self._get_category(organization=org)
        cat2 = self._create_category(name='New category', organization=org)
        self._create_build(organization=org, category=cat1, os=self.os)
        try:
            self._create_build(organization=org, category=cat2, os=self.os)
        except ValidationError as e:
            self.assertIn('os', e.message_dict)
        else:
            self.fail('ValidationError not raised')
        self.assertEqual(Build.objects.count(), 1)

    def test_fw_str(self):
        fw = self._create_firmware_image()
        self.assertIn(str(fw.build), str(fw))
        self.assertIn(fw.build.category.name, str(fw))

    def test_fw_str_new(self):
        fw = FirmwareImage()
        self.assertIsNotNone(str(fw))

    def test_fw_auto_type(self):
        fw = self._create_firmware_image(type='')
        self.assertEqual(fw.type, self.TPLINK_4300_IMAGE)

    def test_device_firmware_image_invalid_org(self):
        device_fw = self._create_device_firmware()
        org2 = self._create_org(name='org2')
        build2 = self._create_build(organization=org2)
        img2 = self._create_firmware_image(build=build2)

        device_fw.image = img2
        try:
            device_fw.full_clean()
        except ValidationError as e:
            self.assertIn('image', e.message_dict)
        else:
            self.fail('ValidationError not raised')

    def test_device_fw_image_changed(self, *args):
        with mock.patch(
            f'{self.app_label}.models.UpgradeOperation.upgrade', return_value=None
        ):
            device_fw = DeviceFirmware()
            self.assertIsNone(device_fw._old_image)
            # save
            device_fw = self._create_device_firmware(upgrade=False)
            self.assertEqual(device_fw._old_image, device_fw.image)
            self.assertEqual(UpgradeOperation.objects.count(), 0)
            # init
            device_fw = DeviceFirmware.objects.first()
            self.assertEqual(device_fw._old_image, device_fw.image)
            # change
            build2 = self._create_build(
                category=device_fw.image.build.category, version='0.2'
            )
            fw2 = self._create_firmware_image(build=build2, type=device_fw.image.type)
            old_image = device_fw.image
            device_fw.image = fw2
            self.assertNotEqual(device_fw._old_image, device_fw.image)
            self.assertEqual(device_fw._old_image, old_image)
            device_fw.full_clean()
            device_fw.save()
            self.assertEqual(UpgradeOperation.objects.count(), 1)
            self.assertEqual(BatchUpgradeOperation.objects.count(), 0)

    def test_device_fw_created(self, *args):
        with mock.patch(
            f'{self.app_label}.models.UpgradeOperation.upgrade', return_value=None
        ):
            self._create_device_firmware(upgrade=True)
            self.assertEqual(UpgradeOperation.objects.count(), 1)
            self.assertEqual(BatchUpgradeOperation.objects.count(), 0)

    def test_device_fw_image_saved_not_installed(self, *args):
        with mock.patch(
            f'{self.app_label}.models.UpgradeOperation.upgrade', return_value=None
        ):
            device_fw = DeviceFirmware()
            self.assertIsNone(device_fw._old_image)
            # save
            device_fw = self._create_device_firmware(upgrade=False, installed=False)
            self.assertEqual(device_fw._old_image, device_fw.image)
            self.assertEqual(UpgradeOperation.objects.count(), 0)
            device_fw.full_clean()
            device_fw.save()
            self.assertEqual(UpgradeOperation.objects.count(), 1)
            self.assertEqual(BatchUpgradeOperation.objects.count(), 0)

    def test_device_fw_no_connection(self):
        try:
            self._create_device_firmware(device_connection=False)
        except ValidationError as e:
            self.assertIn('related connection', str(e))
        else:
            self.fail('ValidationError not raised')

    def test_invalid_board(self):
        image = FIRMWARE_IMAGE_MAP[
            'ar71xx-generic-tl-wdr4300-v1-squashfs-sysupgrade.bin'
        ]
        boards = image['boards']
        del image['boards']
        err = None
        try:
            self._create_firmware_image()
        except ValidationError as e:
            err = e
        image['boards'] = boards
        if err:
            self.assertIn('type', err.message_dict)
            self.assertIn('not find boards', str(err))
        else:
            self.fail('ValidationError not raised')

    def test_custom_image_type_present(self):
        t = FirmwareImage._meta.get_field('type')
        custom_images = app_settings.CUSTOM_OPENWRT_IMAGES
        self.assertEqual(t.choices[0][0], custom_images[0][0])

    def test_device_firmware_image_invalid_model(self):
        device_fw = self._create_device_firmware()
        different_img = self._create_firmware_image(
            build=device_fw.image.build, type=self.TPLINK_4300_IL_IMAGE
        )
        try:
            device_fw.image = different_img
            device_fw.full_clean()
        except ValidationError as e:
            self.assertIn('model do not match', str(e))
        else:
            self.fail('ValidationError not raised')

    def test_upgrade_operation_log_line(self):
        device_fw = self._create_device_firmware()
        uo = UpgradeOperation(device=device_fw.device, image=device_fw.image)
        uo.log_line('line1', save=False)
        uo.log_line('line2', save=False)
        self.assertEqual(uo.log, 'line1\nline2')
        try:
            uo.refresh_from_db()
        except UpgradeOperation.DoesNotExist:
            pass
        else:
            self.fail('item has been saved')

    def test_upgrade_operation_log_line_save(self):
        device_fw = self._create_device_firmware()
        uo = UpgradeOperation(device=device_fw.device, image=device_fw.image)
        uo.log_line('line1')
        uo.log_line('line2')
        uo.refresh_from_db()
        self.assertEqual(uo.log, 'line1\nline2')

    def test_permissions(self):
        admin = Group.objects.get(name='Administrator')
        operator = Group.objects.get(name='Operator')

        admin_permissions = [
            p['codename'] for p in admin.permissions.values('codename')
        ]
        operator_permissions = [
            p['codename'] for p in operator.permissions.values('codename')
        ]

        operators_read_only_admins_manage = [
            'build',
            'devicefirmware',
            'firmwareimage',
            'batchupgradeoperation',
            'upgradeoperation',
        ]
        admins_can_manage = ['category']
        manage_operations = ['add', 'change', 'delete']

        for action in manage_operations:
            for model_name in admins_can_manage:
                codename = '{}_{}'.format(action, model_name)
                self.assertIn(codename, admin_permissions)
                self.assertNotIn(codename, operator_permissions)

        for model_name in operators_read_only_admins_manage:
            codename = 'view_{}'.format(model_name)
            self.assertIn(codename, operator_permissions)

            for action in manage_operations:
                codename = '{}_{}'.format(action, model_name)
                self.assertIn(codename, admin_permissions)

    def test_create_for_device_validation_error(self):
        device_fw = self._create_device_firmware()
        device_fw.image.build.os = device_fw.device.os
        device_fw.image.build.save()
        result = DeviceFirmware.create_for_device(device_fw.device)
        self.assertIsNone(result)


class TestModelsTransaction(TestUpgraderMixin, TransactionTestCase):
    _mock_updrade = 'openwisp_firmware_upgrader.upgraders.openwrt.OpenWrt.upgrade'
    _mock_connect = 'openwisp_controller.connection.models.DeviceConnection.connect'
    os = TestModels.os
    image_type = TestModels.image_type

    @mock.patch(_mock_updrade, return_value=True)
    @mock.patch(_mock_connect, return_value=True)
    def test_dry_run(self, *args):
        env = self._create_upgrade_env()
        # check pending upgrades
        result = BatchUpgradeOperation.dry_run(build=env['build1'])
        self.assertEqual(
            list(result['device_firmwares']),
            list(DeviceFirmware.objects.all().order_by('-created')),
        )
        self.assertEqual(list(result['devices']), [])
        # upgrade devices
        env['build1'].batch_upgrade(firmwareless=True)
        # check pending upgrades again
        result = BatchUpgradeOperation.dry_run(build=env['build1'])
        self.assertEqual(list(result['device_firmwares']), [])
        self.assertEqual(list(result['devices']), [])

    @mock.patch(_mock_updrade, return_value=True)
    @mock.patch(_mock_connect, return_value=True)
    def test_upgrade_related_devices(self, *args):
        env = self._create_upgrade_env()
        # check everything is as expected
        self.assertEqual(UpgradeOperation.objects.count(), 0)
        self.assertEqual(env['d1'].devicefirmware.image, env['image1a'])
        self.assertEqual(env['d2'].devicefirmware.image, env['image1b'])
        # upgrade all related
        env['build2'].batch_upgrade(firmwareless=False)
        # ensure image is changed
        env['d1'].devicefirmware.refresh_from_db()
        env['d2'].devicefirmware.refresh_from_db()
        self.assertEqual(env['d1'].devicefirmware.image, env['image2a'])
        self.assertEqual(env['d2'].devicefirmware.image, env['image2b'])
        # ensure upgrade operation objects have been created
        self.assertEqual(UpgradeOperation.objects.count(), 2)
        batch_qs = BatchUpgradeOperation.objects.all()
        self.assertEqual(batch_qs.count(), 1)
        batch = batch_qs.first()
        self.assertEqual(batch.upgradeoperation_set.count(), 2)
        self.assertEqual(batch.build, env['build2'])
        self.assertEqual(batch.status, 'success')

    @mock.patch(_mock_updrade, return_value=True)
    @mock.patch(_mock_connect, return_value=True)
    def test_upgrade_firmwareless_devices(self, *args):
        env = self._create_upgrade_env(device_firmware=False)
        # check everything is as expected
        self.assertEqual(UpgradeOperation.objects.count(), 0)
        self.assertFalse(hasattr(env['d1'], 'devicefirmware'))
        self.assertFalse(hasattr(env['d2'], 'devicefirmware'))
        # upgrade all related
        env['build2'].batch_upgrade(firmwareless=True)
        env['d1'].refresh_from_db()
        env['d2'].refresh_from_db()
        self.assertEqual(env['d1'].devicefirmware.image, env['image2a'])
        self.assertEqual(env['d2'].devicefirmware.image, env['image2b'])
        # ensure upgrade operation objects have been created
        self.assertEqual(UpgradeOperation.objects.count(), 2)
        batch_qs = BatchUpgradeOperation.objects.all()
        self.assertEqual(batch_qs.count(), 1)
        batch = batch_qs.first()
        self.assertEqual(batch.upgradeoperation_set.count(), 2)
        self.assertEqual(batch.build, env['build2'])
        self.assertEqual(batch.status, 'success')

    @mock.patch.object(upgrade_firmware, 'max_retries', 0)
    def test_batch_upgrade_failure(self):
        env = self._create_upgrade_env()
        with redirect_stdout(io.StringIO()):
            env['build2'].batch_upgrade(firmwareless=False)
        batch = BatchUpgradeOperation.objects.first()
        self.assertEqual(batch.status, 'failed')
        self.assertEqual(BatchUpgradeOperation.objects.count(), 1)

    @mock.patch(_mock_updrade, return_value=True)
    @mock.patch(_mock_connect, return_value=True)
    def test_upgrade_related_devices_existing_fw(self, *args):
        env = self._create_upgrade_env()
        self.assertEqual(UpgradeOperation.objects.count(), 0)
        self.assertEqual(env['d1'].devicefirmware.image, env['image1a'])
        self.assertEqual(env['d2'].devicefirmware.image, env['image1b'])
        env['d1'].devicefirmware.installed = False
        env['d1'].devicefirmware.save(upgrade=False)
        env['d2'].devicefirmware.installed = False
        env['d2'].devicefirmware.save(upgrade=False)
        env['build1'].batch_upgrade(firmwareless=False)
        env['d1'].devicefirmware.refresh_from_db()
        env['d2'].devicefirmware.refresh_from_db()
        self.assertEqual(env['d1'].devicefirmware.image, env['image1a'])
        self.assertEqual(env['d2'].devicefirmware.image, env['image1b'])
        self.assertEqual(UpgradeOperation.objects.count(), 2)
        batch_qs = BatchUpgradeOperation.objects.all()
        self.assertEqual(batch_qs.count(), 1)
        batch = batch_qs.first()
        self.assertEqual(batch.upgradeoperation_set.count(), 2)
        self.assertEqual(batch.build, env['build1'])
        self.assertEqual(batch.status, 'success')

    def test_upgrade_retried(self):
        env = self._create_upgrade_env()
        try:
            with redirect_stdout(io.StringIO()):
                env['build2'].batch_upgrade(firmwareless=False)
        except Retry:
            pass
        except Exception as e:
            self.fail(f'Expected retry, got {e.__class__} instead')
        else:
            self.fail('Retry exception not raised')
        self.assertEqual(BatchUpgradeOperation.objects.count(), 1)
        batch = BatchUpgradeOperation.objects.first()
        self.assertEqual(batch.status, 'in-progress')

    def test_device_fw_not_created_on_device_connection_save(self):
        org = self._get_org()
        category = self._get_category(organization=org)
        build1 = self._create_build(category=category, version='0.1', os=self.os)
        image1a = self._create_firmware_image(build=build1, type=self.image_type)

        with self.subTest("Device doesn't define os"):
            d1 = self._create_device_with_connection(os='', model=image1a.boards[0])
            self.assertEqual(DeviceConnection.objects.count(), 1)
            self.assertEqual(Device.objects.count(), 1)
            self.assertEqual(DeviceFirmware.objects.count(), 0)
            d1.delete()
            Credentials.objects.all().delete()

        with self.subTest("Device doesn't define model"):
            d1 = self._create_device_with_connection(os=self.os, model='')
            self.assertEqual(DeviceConnection.objects.count(), 1)
            self.assertEqual(Device.objects.count(), 1)
            self.assertEqual(DeviceFirmware.objects.count(), 0)
            d1.delete()
            Credentials.objects.all().delete()

        build1.os = None
        build1.save()

        with self.subTest("Build doesn't define os"):
            d1 = self._create_device_with_connection(
                model=image1a.boards[0], os=self.os
            )
            self.assertEqual(DeviceConnection.objects.count(), 1)
            self.assertEqual(Device.objects.count(), 1)
            self.assertEqual(DeviceFirmware.objects.count(), 0)

    def test_device_fw_created_on_device_connection_save(self):
        self.assertEqual(DeviceFirmware.objects.count(), 0)
        self.assertEqual(Device.objects.count(), 0)
        org = self._get_org()
        category = self._get_category(organization=org)
        build1 = self._create_build(category=category, version='0.1', os=self.os)
        image1a = self._create_firmware_image(build=build1, type=self.image_type)
        self._create_device_with_connection(os=self.os, model=image1a.boards[0])
        self.assertEqual(Device.objects.count(), 1)
        self.assertEqual(DeviceFirmware.objects.count(), 1)
        self.assertEqual(DeviceConnection.objects.count(), 1)
