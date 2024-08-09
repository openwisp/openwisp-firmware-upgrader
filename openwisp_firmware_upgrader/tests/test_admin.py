import json
from datetime import timedelta
from unittest import mock

import swapper
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import RequestFactory, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils.timezone import localtime

from openwisp_controller.config.tests.test_admin import TestAdmin as TestConfigAdmin
from openwisp_controller.connection import settings as conn_settings
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
from openwisp_utils.tests import AdminActionPermTestMixin, capture_stderr

from ..hardware import REVERSE_FIRMWARE_IMAGE_MAP
from ..swapper import load_model
from ..upgraders.openwisp import OpenWisp1
from .base import TestUpgraderMixin

User = get_user_model()

Build = load_model('Build')
Category = load_model('Category')
DeviceFirmware = load_model('DeviceFirmware')
FirmwareImage = load_model('FirmwareImage')
UpgradeOperation = load_model('UpgradeOperation')
BatchUpgradeOperation = load_model('BatchUpgradeOperation')
Device = swapper.load_model('config', 'Device')


class MockRequest:
    pass


class BaseTestAdmin(TestMultitenantAdminMixin, TestUpgraderMixin):
    app_label = 'firmware_upgrader'
    _device_params = TestConfigAdmin._device_params.copy()
    _device_params.update(
        {
            'devicefirmware-0-image': '',
            'devicefirmware-0-id': '',
            'devicefirmware-TOTAL_FORMS': 0,
            'devicefirmware-INITIAL_FORMS': 0,
            'devicefirmware-MIN_NUM_FORMS': 0,
            'devicefirmware-MAX_NUM_FORMS': 1,
            'deviceconnection_set-TOTAL_FORMS': 1,
            'deviceconnection_set-INITIAL_FORMS': 1,
            'devicelocation-TOTAL_FORMS': 1,
            'devicelocation-INITIAL_FORMS': 0,
            'devicelocation-MIN_NUM_FORMS': 0,
            'devicelocation-MAX_NUM_FORMS': 1,
            'config-INITIAL_FORMS': 1,
        }
    )

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
        with self.assertNumQueries(13):
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

    def test_view_device_administrator(self):
        device_fw = self._create_device_firmware()
        org = self._get_org()
        self._create_administrator(organizations=[org])
        self._login(username='administrator', password='tester')
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

    def test_admin_menu_groups(self):
        # Test menu group (openwisp-utils menu group) for Build, Category,
        # BatchUpgradeOperation models
        self._login()
        models = ['build', 'category', 'batchupgradeoperation']
        response = self.client.get(reverse('admin:index'))
        for model in models:
            with self.subTest(f'test menu group link {model} model'):
                url = reverse(f'admin:{self.app_label}_{model}_changelist')
                self.assertContains(response, f'class="mg-link" href="{url}"')
        with self.subTest('test firmware group is registered'):
            self.assertContains(
                response,
                '<div class="mg-dropdown-label">Firmware </div>',
                html=True,
            )

    def test_save_device_with_deleted_devicefirmware(self):
        self._login()
        device_fw = self._create_device_firmware()
        device = device_fw.device
        device_conn = device.deviceconnection_set.first()
        device_params = self._device_params.copy()
        device_params.update(
            {
                'devicefirmware-0-image': str(device_fw.image_id),
                'devicefirmware-0-id': str(device_fw.id),
                'organization': str(device.organization.id),
                'config-0-id': str(device.config.pk),
                'config-0-device': str(device.id),
                'deviceconnection_set-0-credentials': str(device_conn.credentials_id),
                'deviceconnection_set-0-id': str(device_conn.id),
                'devicefirmware-TOTAL_FORMS': 1,
                'devicefirmware-INITIAL_FORMS': 1,
            }
        )
        FirmwareImage.objects.all().delete()
        response = self.client.post(
            reverse('admin:config_device_change', args=[device.id]),
            data=device_params,
            follow=True,
        )
        self.assertEqual(response.status_code, 200)

    @capture_stderr()
    @mock.patch(
        'openwisp_firmware_upgrader.utils.get_upgrader_class_from_device_connection'
    )
    def test_device_firmware_upgrade_without_device_connection(
        self, captured_stderr, mocked_func, *args
    ):
        self._login()
        device_fw = self._create_device_firmware()
        device = device_fw.device
        device.deviceconnection_set.all().delete()
        response = self.client.get(
            reverse('admin:config_device_change', args=[device.id])
        )
        self.assertNotIn(
            '\'NoneType\' object has no attribute \'update_strategy\'',
            captured_stderr.getvalue(),
        )
        mocked_func.assert_not_called()
        self.assertEqual(response.status_code, 200)

    def test_deactivated_firmware_image_inline(self):
        self._login()
        device = self._create_config(organization=self._get_org()).device
        device.deactivate()
        response = self.client.get(
            reverse('admin:config_device_change', args=[device.id])
        )
        # Check that it is not possible to add a DeviceFirmwareImage to a
        # deactivated device in the admin interface.
        self.assertContains(
            response,
            '<input type="hidden" name="devicefirmware-MAX_NUM_FORMS"'
            ' value="0" id="id_devicefirmware-MAX_NUM_FORMS">',
        )
        self._create_device_firmware(device=device)
        response = self.client.get(
            reverse('admin:config_device_change', args=[device.id])
        )
        # Ensure that a deactivated device's existing DeviceFirmwareImage
        # is displayed as readonly in the admin interface.
        self.assertContains(
            response,
            '<div class="readonly">Test Category v0.1:'
            ' TP-Link WDR4300 v1 (OpenWrt 19.07 and later)</div>',
        )
        self.assertNotContains(
            response,
            '<select name="devicefirmware-0-image" id="id_devicefirmware-0-image">',
        )


_mock_updrade = 'openwisp_firmware_upgrader.upgraders.openwrt.OpenWrt.upgrade'
_mock_connect = 'openwisp_controller.connection.models.DeviceConnection.connect'


@mock.patch(_mock_updrade, return_value=True)
@mock.patch(_mock_connect, return_value=True)
class TestAdminTransaction(
    BaseTestAdmin, AdminActionPermTestMixin, TransactionTestCase
):
    def test_upgrade_selected_action_perms(self, *args):
        env = self._create_upgrade_env()
        org = env['d1'].organization
        self._create_firmwareless_device(organization=org)
        user = self._create_user(is_staff=True)
        self._create_org_user(user=user, organization=org, is_admin=True)
        # The user is redirected to the BatchUpgradeOperation page after success operation.
        # Thus, we need to add the permission to the user.
        user.user_permissions.add(
            Permission.objects.get(
                codename=f'change_{BatchUpgradeOperation._meta.model_name}'
            )
        )
        self._test_action_permission(
            path=self.build_list_url,
            action='upgrade_selected',
            user=user,
            obj=env['build1'],
            message=(
                'You can track the progress of this mass upgrade operation '
                'in this page. Refresh the page from time to time to check '
                'its progress.'
            ),
            required_perms=['change'],
            extra_payload={
                'upgrade_all': 'upgrade_all',
                'upgrade_options': '{"c": true}',
            },
        )

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

        with self.subTest('Invalid upgrade_options'):
            response = self.client.post(
                self.build_list_url,
                {
                    'action': 'upgrade_selected',
                    'upgrade_related': 'upgrade_related',
                    'upgrade_options': 'invalid',
                    ACTION_CHECKBOX_NAME: (env['build2'].pk,),
                },
                follow=True,
            )
            self.assertContains(
                response, '<ul class="errorlist"><li>Enter a valid JSON.</li></ul>'
            )

        with self.subTest('Test with valid upgrade_options'):
            r = self.client.post(
                self.build_list_url,
                {
                    'action': 'upgrade_selected',
                    'upgrade_related': 'upgrade_related',
                    'upgrade_options': '{"c": true}',
                    ACTION_CHECKBOX_NAME: (env['build2'].pk,),
                },
                follow=True,
            )
            self.assertContains(r, '<li class="success">')
            self.assertContains(r, 'track the progress')
            self.assertEqual(
                UpgradeOperation.objects.filter(upgrade_options={'c': True}).count(), 2
            )
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

        with self.subTest('Invalid upgrade_options'):
            response = self.client.post(
                self.build_list_url,
                {
                    'action': 'upgrade_selected',
                    'upgrade_all': 'upgrade_all',
                    'upgrade_options': 'invalid',
                    ACTION_CHECKBOX_NAME: (env['build2'].pk,),
                },
                follow=True,
            )
            self.assertEqual(response.status_code, 200)
            self.assertContains(
                response, '<ul class="errorlist"><li>Enter a valid JSON.</li></ul>'
            )

        with self.subTest('Test with valid upgrade_options'):
            response = self.client.post(
                self.build_list_url,
                {
                    'action': 'upgrade_selected',
                    'upgrade_all': 'upgrade_all',
                    'upgrade_options': '{"c": true}',
                    ACTION_CHECKBOX_NAME: (env['build2'].pk,),
                },
                follow=True,
            )
            self.assertContains(response, '<li class="success">')
            self.assertContains(response, 'track the progress')
            self.assertEqual(
                UpgradeOperation.objects.filter(upgrade_options={'c': True}).count(), 3
            )
            self.assertEqual(fw.count(), 3)
            self.assertContains(
                response,
                (
                    '<div class="readonly"><ul class="readonly-upgrade-options">'
                    '<li><img src="/static/admin/img/icon-yes.svg" alt="yes">'
                    'Attempt to preserve all changed files in /etc/ (-c)</li>'
                    '<li><img src="/static/admin/img/icon-no.svg" alt="no">'
                    'Attempt to preserve all changed files in /, except those from '
                    'packages but including changed confs. (-o)</li>'
                    '<li><img src="/static/admin/img/icon-no.svg" alt="no">'
                    'Do not save configuration over reflash (-n)</li>'
                    '<li><img src="/static/admin/img/icon-no.svg" alt="no">'
                    'Skip from backup files that are equal to those in /rom (-u)</li>'
                    '<li><img src="/static/admin/img/icon-no.svg" alt="no">'
                    'Do not attempt to restore the partition table after flash. (-p)</li>'
                    '<li><img src="/static/admin/img/icon-no.svg" alt="no">'
                    'Include in backup a list of current installed packages at '
                    '/etc/backup/installed_packages.txt (-k)</li>'
                    '<li><img src="/static/admin/img/icon-no.svg" alt="no">'
                    'Flash image even if image checks fail, this is dangerous! (-F)</li></ul></div>'
                ),
                html=True,
            )

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

    def test_device_firmware_upgrade_options(self, *args):
        self._login()
        device_fw = self._create_device_firmware()
        device = device_fw.device
        device_conn = device.deviceconnection_set.first()
        device_params = self._device_params.copy()
        build = self._create_build(version='0.2')
        image = self._create_firmware_image(build=build)
        upgrade_options = {
            'c': True,
            'o': False,
            'u': False,
            'n': False,
            'p': False,
            'k': False,
            'F': True,
        }
        device_params.update(
            {
                'model': device.model,
                'devicefirmware-0-image': str(image.id),
                'devicefirmware-0-id': str(device_fw.id),
                'devicefirmware-0-upgrade_options': json.dumps(upgrade_options),
                'organization': str(device.organization.id),
                'config-0-id': str(device.config.pk),
                'config-0-device': str(device.id),
                'deviceconnection_set-0-credentials': str(device_conn.credentials_id),
                'deviceconnection_set-0-id': str(device_conn.id),
                'deviceconnection_set-0-update_strategy': conn_settings.DEFAULT_UPDATE_STRATEGIES[
                    0
                ][
                    0
                ],
                'deviceconnection_set-0-enabled': True,
                'devicefirmware-TOTAL_FORMS': 1,
                'devicefirmware-INITIAL_FORMS': 1,
                'upgradeoperation_set-TOTAL_FORMS': 0,
                'upgradeoperation_set-INITIAL_FORMS': 0,
                'upgradeoperation_set-MIN_NUM_FORMS': 0,
                'upgradeoperation_set-MAX_NUM_FORMS': 0,
                '_continue': True,
            }
        )
        response = self.client.post(
            reverse('admin:config_device_change', args=[device.id]),
            data=device_params,
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(device.upgradeoperation_set.count(), 1)
        upgrade_operation = device.upgradeoperation_set.first()
        self.assertEqual(upgrade_operation.upgrade_options, upgrade_options)
        self.assertContains(
            response,
            (
                '<div class="readonly"><ul class="readonly-upgrade-options"><li>'
                '<img src="/static/admin/img/icon-yes.svg" alt="yes">'
                'Attempt to preserve all changed files in /etc/ (-c)</li>'
                '<li><img src="/static/admin/img/icon-no.svg" alt="no">'
                'Attempt to preserve all changed files in /, except those from packages '
                'but including changed confs. (-o)</li>'
                '<li><img src="/static/admin/img/icon-no.svg" '
                'alt="no">Do not save configuration over reflash (-n)</li>'
                '<li><img src="/static/admin/img/icon-no.svg" alt="no">Skip from backup files '
                'that are equal to those in /rom (-u)</li>'
                '<li><img src="/static/admin/img/icon-no.svg" alt="no">'
                'Do not attempt to restore the partition table after flash. (-p)</li>'
                '<li><img src="/static/admin/img/icon-no.svg" alt="no">'
                'Include in backup a list of current installed packages at '
                '/etc/backup/installed_packages.txt (-k)</li>'
                '<li><img src="/static/admin/img/icon-yes.svg" alt="yes">'
                'Flash image even if image checks fail, this is dangerous! (-F)</li></ul></div>'
            ),
            html=True,
        )

    @mock.patch.object(OpenWisp1, 'SCHEMA', None)
    def test_using_upgrade_options_with_unsupported_upgrader(self, *args):
        self._login()
        device_fw = self._create_device_firmware()
        device = device_fw.device
        device.config.backend = 'netjsonconfig.OpenWisp'
        device.config.save()
        device_conn = device.deviceconnection_set.first()
        device_conn.update_strategy = conn_settings.DEFAULT_UPDATE_STRATEGIES[1][0]
        device_conn.save()
        device_params = self._device_params.copy()
        build = self._create_build(version='0.2')
        image = self._create_firmware_image(build=build)
        upgrade_options = {
            'c': True,
            'o': False,
            'u': False,
            'n': False,
            'p': False,
            'k': False,
            'F': True,
        }
        device_params.update(
            {
                'model': device.model,
                'devicefirmware-0-image': str(image.id),
                'devicefirmware-0-id': str(device_fw.id),
                'devicefirmware-0-upgrade_options': json.dumps(upgrade_options),
                'organization': str(device.organization.id),
                'config-0-id': str(device.config.pk),
                'config-0-device': str(device.id),
                'deviceconnection_set-0-credentials': str(device_conn.credentials_id),
                'deviceconnection_set-0-id': str(device_conn.id),
                'deviceconnection_set-0-update_strategy': (
                    conn_settings.DEFAULT_UPDATE_STRATEGIES[1][0]
                ),
                'deviceconnection_set-0-enabled': True,
                'devicefirmware-TOTAL_FORMS': 1,
                'devicefirmware-INITIAL_FORMS': 1,
                'upgradeoperation_set-TOTAL_FORMS': 0,
                'upgradeoperation_set-INITIAL_FORMS': 0,
                'upgradeoperation_set-MIN_NUM_FORMS': 0,
                'upgradeoperation_set-MAX_NUM_FORMS': 0,
                '_continue': True,
            }
        )

        with self.subTest('Test DeviceFirmwareInline does not have schema defined'):
            response = self.client.get(
                reverse('admin:config_device_change', args=[device.id])
            )
            self.assertContains(
                response, '<script>\nvar firmwareUpgraderSchema = null\n</script>'
            )

        with self.subTest('Test using upgrade options with unsupported upgrader'):
            response = self.client.post(
                reverse('admin:config_device_change', args=[device.id]),
                data=device_params,
                follow=True,
            )
            self.assertContains(
                response,
                (
                    '<ul class="errorlist nonfield"><li>Using upgrade '
                    'options is not allowed with this upgrader.</li></ul>'
                ),
            )

        with self.subTest('Test upgrading without upgrade options'):
            del device_params['devicefirmware-0-upgrade_options']
            response = self.client.post(
                reverse('admin:config_device_change', args=[device.id]),
                data=device_params,
                follow=True,
            )
            self.assertContains(
                response,
                (
                    '<div class="readonly">Upgrade options are '
                    'not supported for this upgrader.</div>'
                ),
            )


del TestConfigAdmin
