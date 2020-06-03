from unittest import mock

from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from openwisp_firmware_upgrader.admin import (
    BuildAdmin,
    DeviceAdmin,
    DeviceFirmwareInline,
    FirmwareImageInline,
    admin,
)

from openwisp_controller.config.models import Device
from openwisp_users.tests.utils import TestMultitenantAdminMixin

from ..swapper import load_model
from .base import TestUpgraderMixin

User = get_user_model()

Build = load_model('Build')
Category = load_model('Category')
DeviceFirmware = load_model('DeviceFirmware')
FirmwareImage = load_model('FirmwareImage')
UpgradeOperation = load_model('UpgradeOperation')


class MockRequest:
    pass


class BaseTestAdmin(TestMultitenantAdminMixin, TestUpgraderMixin):
    app_label = 'firmware_upgrader'

    @property
    def build_list_url(self):
        return reverse(f'admin:{self.app_label}_build_changelist')


class TestAdmin(BaseTestAdmin, TestCase):
    def test_build_list(self):
        self._login()
        build = self._create_build()
        r = self.client.get(self.build_list_url)
        self.assertContains(r, str(build))

    def test_build_list_upgrade_action(self):
        self._login()
        self._create_build()
        r = self.client.get(self.build_list_url)
        self.assertContains(r, '<option value="upgrade_selected">')

    def test_upgrade_selected_error(self):
        self._login()
        b1 = self._create_build()
        b2 = self._create_build(version='0.2', category=b1.category)
        r = self.client.post(
            self.build_list_url,
            {'action': 'upgrade_selected', ACTION_CHECKBOX_NAME: (b1.pk, b2.pk)},
            follow=True,
        )
        self.assertContains(r, '<li class="error">')
        self.assertContains(
            r, 'only a single mass upgrade operation at time is supported'
        )

    def test_upgrade_intermediate_page_related(self):
        self._login()
        env = self._create_upgrade_env()
        with self.assertNumQueries(14):
            r = self.client.post(
                self.build_list_url,
                {
                    'action': 'upgrade_selected',
                    ACTION_CHECKBOX_NAME: (env['build2'].pk,),
                },
                follow=True,
            )
        self.assertContains(r, 'Devices related to build')
        self.assertNotContains(r, 'has never upgraded yet')
        self.assertNotContains(r, '<input type="submit" name="upgrade_related"')

    def test_upgrade_intermediate_page_firmwareless(self):
        self._login()
        env = self._create_upgrade_env(device_firmware=False)
        with self.assertNumQueries(12):
            r = self.client.post(
                self.build_list_url,
                {
                    'action': 'upgrade_selected',
                    ACTION_CHECKBOX_NAME: (env['build2'].pk,),
                },
                follow=True,
            )
        self.assertNotContains(r, 'Devices related to build')
        self.assertContains(r, 'has never upgraded yet')
        self.assertNotContains(r, '<input type="submit" name="upgrade_related"')
        self.assertContains(r, '<input type="submit" name="upgrade_all"')

    def test_view_device_operator(self):
        device_fw = self._create_device_firmware()
        org = self._get_org()
        self._create_operator(organizations=[org])
        self._login(username='operator', password='tester')
        url = reverse('admin:config_device_change', args=[device_fw.device_id])
        r = self.client.get(url)
        self.assertContains(r, str(device_fw.image_id))

    def test_firmware_image_has_change_permission(self):
        request = MockRequest()
        request.user = User.objects.first()
        env = self._create_upgrade_env()
        self.assertIn(FirmwareImageInline, BuildAdmin.inlines)
        inline = FirmwareImageInline(FirmwareImage, admin.site)
        self.assertIsInstance(inline, FirmwareImageInline)
        self.assertIs(inline.has_change_permission(request), True)
        self.assertIs(inline.has_change_permission(request, obj=env['image1a']), False)

    def test_device_firmware_inline_has_add_permission(self):
        request = MockRequest()
        request.user = User.objects.first()
        device_fw = self._create_device_firmware()
        device = device_fw.device
        inline = DeviceFirmwareInline(Device, admin.site)
        self.assertTrue(inline.has_add_permission(request, obj=None))
        self.assertTrue(inline.has_add_permission(request, obj=device))
        self.assertIsInstance(inline, DeviceFirmwareInline)
        self.assertIn(DeviceFirmwareInline, DeviceAdmin.inlines)

    def test_device_firmware_admin_get_inlines(self):
        device_fw = self._create_device_firmware()
        device = device_fw.device
        request = MockRequest()
        request.user = User.objects.first()
        deviceadmin = DeviceAdmin(model=Device, admin_site=admin.site)
        self.assertNotIn(
            DeviceFirmwareInline, deviceadmin.get_inlines(request, obj=None)
        )
        self.assertIn(
            DeviceFirmwareInline, deviceadmin.get_inlines(request, obj=device)
        )


_mock_updrade = 'openwisp_firmware_upgrader.upgraders.openwrt.OpenWrt.upgrade'
_mock_connect = 'openwisp_controller.connection.models.DeviceConnection.connect'


@mock.patch(_mock_updrade, return_value=True)
@mock.patch(_mock_connect, return_value=True)
class TestAdminTransaction(BaseTestAdmin, TransactionTestCase):
    def test_upgrade_related(self, *args):
        self._login()
        env = self._create_upgrade_env()
        self._create_firmwareless_device(organization=env['d1'].organization)
        # check state is good before proceeding
        fw = DeviceFirmware.objects.filter(
            image__build_id=env['build2'].pk
        ).select_related('image')
        self.assertEqual(Device.objects.count(), 3)
        self.assertEqual(UpgradeOperation.objects.count(), 0)
        self.assertEqual(fw.count(), 0)
        r = self.client.post(
            self.build_list_url,
            {
                'action': 'upgrade_selected',
                'upgrade_related': 'upgrade_related',
                ACTION_CHECKBOX_NAME: (env['build2'].pk,),
            },
            follow=True,
        )
        self.assertContains(r, '<li class="success">')
        self.assertContains(r, 'track the progress')
        self.assertEqual(UpgradeOperation.objects.count(), 2)
        self.assertEqual(fw.count(), 2)

    def test_upgrade_all(self, *args):
        self._login()
        env = self._create_upgrade_env()
        self._create_firmwareless_device(organization=env['d1'].organization)
        # check state is good before proceeding
        fw = DeviceFirmware.objects.filter(
            image__build_id=env['build2'].pk
        ).select_related('image')
        self.assertEqual(Device.objects.count(), 3)
        self.assertEqual(UpgradeOperation.objects.count(), 0)
        self.assertEqual(fw.count(), 0)
        r = self.client.post(
            self.build_list_url,
            {
                'action': 'upgrade_selected',
                'upgrade_all': 'upgrade_all',
                ACTION_CHECKBOX_NAME: (env['build2'].pk,),
            },
            follow=True,
        )
        self.assertContains(r, '<li class="success">')
        self.assertContains(r, 'track the progress')
        self.assertEqual(UpgradeOperation.objects.count(), 3)
        self.assertEqual(fw.count(), 3)

    def test_massive_upgrade_operation_page(self, *args):
        self.test_upgrade_all()
        uo = UpgradeOperation.objects.first()
        url = reverse(
            f'admin:{self.app_label}_batchupgradeoperation_change', args=[uo.batch.pk]
        )
        response = self.client.get(url)
        self.assertContains(response, 'Success rate')
        self.assertContains(response, 'Failure rate')
        self.assertContains(response, 'Abortion rate')

    def test_recent_upgrades(self, *args):
        self._login()
        env = self._create_upgrade_env()
        url = reverse('admin:config_device_change', args=[env['d2'].pk])
        r = self.client.get(url)
        self.assertNotContains(r, 'Recent Upgrades')
        env['build2'].batch_upgrade(firmwareless=True)
        r = self.client.get(url)
        self.assertContains(r, 'Recent Upgrades')
