from datetime import timedelta
from unittest import mock

import swapper
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils.timezone import localtime

from openwisp_firmware_upgrader.admin import (
    BuildAdmin,
    DeviceAdmin,
    DeviceFirmwareForm,
    DeviceFirmwareInline,
    DeviceUpgradeOperationInline,
    FirmwareImageInline,
    admin,
)
from openwisp_users.tests.utils import TestMultitenantAdminMixin

from ..hardware import REVERSE_FIRMWARE_IMAGE_MAP
from ..swapper import load_model
from .base import TestUpgraderMixin

User = get_user_model()

Build = load_model('Build')
Category = load_model('Category')
DeviceFirmware = load_model('DeviceFirmware')
FirmwareImage = load_model('FirmwareImage')
UpgradeOperation = load_model('UpgradeOperation')
Device = swapper.load_model('config', 'Device')


class MockRequest:
    pass


class BaseTestAdmin(TestMultitenantAdminMixin, TestUpgraderMixin):
    app_label = 'firmware_upgrader'

    def setUp(self, *args, **kwargs):
        super().setUp(*args, **kwargs)
        self.factory = RequestFactory()

    def make_device_admin_request(self, pk):
        return self.factory.get(reverse('admin:config_device_change', args=[pk]))

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

    def test_upgrade_build_admin(self):
        self._login()
        b = self._create_build()
        path = reverse(f'admin:{self.app_label}_build_change', args=[b.pk])
        r = self.client.get(path)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Launch mass upgrade operation')

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
        with self.assertNumQueries(17):
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
        with self.assertNumQueries(15):
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
        device_fw = self._create_device_firmware()
        device = device_fw.device
        request = self.make_device_admin_request(device.pk)
        request.user = User.objects.first()
        inline = DeviceFirmwareInline(Device, admin.site)
        self.assertTrue(inline.has_add_permission(request, obj=None))
        self.assertTrue(inline.has_add_permission(request, obj=device))
        self.assertIsInstance(inline, DeviceFirmwareInline)
        deviceadmin = DeviceAdmin(model=Device, admin_site=admin.site)
        self.assertIn(
            DeviceFirmwareInline, deviceadmin.get_inlines(request, obj=device)
        )

    def test_device_firmware_inline(self):
        device_fw = self._create_device_firmware()
        device = device_fw.device
        request = self.make_device_admin_request(device.pk)
        request.user = User.objects.first()
        deviceadmin = DeviceAdmin(model=Device, admin_site=admin.site)
        self.assertNotIn(
            DeviceFirmwareInline, deviceadmin.get_inlines(request, obj=None)
        )
        self.assertIn(
            DeviceFirmwareInline, deviceadmin.get_inlines(request, obj=device)
        )

    def _prepare_image_qs_test_env(self):
        device_fw = self._create_device_firmware()
        device = device_fw.device
        request = self.make_device_admin_request(device.pk)
        request.user = User.objects.first()
        org2 = self._create_org(name='org2', slug='org2')
        category_org2 = self._create_category(organization=org2, name='org2')
        build_org2 = self._create_build(category=category_org2)
        img_org2 = self._create_firmware_image(build=build_org2)
        yuncore = self._create_firmware_image(
            build=device_fw.image.build,
            type=REVERSE_FIRMWARE_IMAGE_MAP['YunCore XD3200'],
        )
        mesh_category = self._create_category(
            name='mesh', organization=device.organization
        )
        mesh_build = self._create_build(category=mesh_category)
        mesh_image = self._create_firmware_image(build=mesh_build)
        return device, device_fw, img_org2, yuncore, mesh_image

    def test_image_queryset_existing_device_firmware(self):
        (
            device,
            device_fw,
            img_org2,
            yuncore,
            mesh_image,
        ) = self._prepare_image_qs_test_env()
        # existing DeviceFirmware
        # restricts images to category of image in used
        form = DeviceFirmwareForm(device=device, instance=device_fw)
        self.assertEqual(form.fields['image'].queryset.count(), 1)
        self.assertIn(device_fw.image, form.fields['image'].queryset)
        self.assertNotIn(img_org2, form.fields['image'].queryset)

    def test_image_queryset_new_device_firmware(self):
        (
            device,
            device_fw,
            img_org2,
            yuncore,
            mesh_image,
        ) = self._prepare_image_qs_test_env()
        # new DeviceFirmware
        # shows all the categories related to the model
        form = DeviceFirmwareForm(device=device)
        self.assertEqual(form.fields['image'].queryset.count(), 2)
        self.assertIn(device_fw.image, form.fields['image'].queryset)
        self.assertIn(mesh_image, form.fields['image'].queryset)
        self.assertNotIn(img_org2, form.fields['image'].queryset)

    def test_image_queryset_no_model(self):
        (
            device,
            device_fw,
            img_org2,
            yuncore,
            mesh_image,
        ) = self._prepare_image_qs_test_env()
        # existing DeviceFirmware
        # if no model specified, get all models available
        device.model = ''
        device.save()
        form = DeviceFirmwareForm(device=device, instance=device_fw)
        self.assertEqual(form.fields['image'].queryset.count(), 2)
        self.assertIn(yuncore, form.fields['image'].queryset)
        self.assertNotIn(img_org2, form.fields['image'].queryset)

    def test_image_queryset_no_model_nor_device_firmware(self):
        (
            device,
            device_fw,
            img_org2,
            yuncore,
            mesh_image,
        ) = self._prepare_image_qs_test_env()
        # new DeviceFirmware, no model
        # returns all devices of the org
        device.model = ''
        device.save()
        form = DeviceFirmwareForm(device=device)
        self.assertEqual(form.fields['image'].queryset.count(), 3)
        self.assertIn(device_fw.image, form.fields['image'].queryset)
        self.assertIn(mesh_image, form.fields['image'].queryset)
        self.assertIn(yuncore, form.fields['image'].queryset)
        self.assertNotIn(img_org2, form.fields['image'].queryset)


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
        self.assertNotContains(r, 'Recent Firmware Upgrades')
        env['build2'].batch_upgrade(firmwareless=True)
        r = self.client.get(url)
        self.assertContains(r, 'Recent Firmware Upgrades')

    def test_upgrade_operation_inline(self, *args):
        device_fw = self._create_device_firmware()
        device_fw.save(upgrade=True)
        device = device_fw.device
        request = self.make_device_admin_request(device.pk)
        request.user = User.objects.first()
        deviceadmin = DeviceAdmin(model=Device, admin_site=admin.site)
        self.assertNotIn(
            DeviceUpgradeOperationInline, deviceadmin.get_inlines(request, obj=None)
        )
        self.assertIn(
            DeviceUpgradeOperationInline, deviceadmin.get_inlines(request, obj=device)
        )

    def test_upgrade_operation_inline_queryset(self, *args):
        device_fw = self._create_device_firmware()
        device_fw.save(upgrade=True)
        # expect only 1
        uo = device_fw.device.upgradeoperation_set.get()
        device = device_fw.device
        request = self.make_device_admin_request(device.pk)
        request.user = User.objects.first()
        inline = DeviceUpgradeOperationInline(Device, admin.site)
        qs = inline.get_queryset(request)
        self.assertEqual(qs.count(), 1)
        self.assertIn(uo, qs)
        uo.created = localtime() - timedelta(days=30)
        uo.modified = uo.created
        uo.save()
        qs = inline.get_queryset(request)
        self.assertEqual(qs.count(), 0)
