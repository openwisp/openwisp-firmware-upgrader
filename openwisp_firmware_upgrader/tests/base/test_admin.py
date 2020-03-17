from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.auth import get_user_model

from openwisp_controller.config.models import Device

User = get_user_model()


class BaseTestAdmin(object):

    def _create_super_admin(self):
        return User.objects.create(username='admin',
                                   password='admin',
                                   email='admin@admin.org',
                                   is_staff=True,
                                   is_superuser=True)

    def _login(self, user=None):
        if not user:
            user = self._create_super_admin()
        self.client.force_login(user)

    def test_build_list(self):
        self._login()
        build = self._create_build()
        r = self.client.get(self.BUILD_LIST_URL)
        self.assertContains(r, str(build))

    def test_build_list_upgrade_action(self):
        self._login()
        self._create_build()
        r = self.client.get(self.BUILD_LIST_URL)
        self.assertContains(r, '<option value="upgrade_selected">')

    def test_upgrade_selected_error(self):
        self._login()
        b1 = self._create_build()
        b2 = self._create_build(version='0.2',
                                category=b1.category)
        r = self.client.post(self.BUILD_LIST_URL, {
            'action': 'upgrade_selected',
            ACTION_CHECKBOX_NAME: (b1.pk, b2.pk)
        }, follow=True)
        self.assertContains(r, '<li class="error">')
        self.assertContains(r, 'only a single mass upgrade operation at time is supported')

    def test_upgrade_intermediate_page_related(self):
        self._login()
        env = self._create_upgrade_env()
        r = self.client.post(self.BUILD_LIST_URL, {
            'action': 'upgrade_selected',
            ACTION_CHECKBOX_NAME: (env['build2'].pk,)
        }, follow=True)
        self.assertContains(r, 'Devices related to build')
        self.assertNotContains(r, 'has never upgraded yet')
        self.assertNotContains(r, '<input type="submit" name="upgrade_related"')

    def test_upgrade_intermediate_page_firmwareless(self):
        self._login()
        env = self._create_upgrade_env(device_firmware=False)
        r = self.client.post(self.BUILD_LIST_URL, {
            'action': 'upgrade_selected',
            ACTION_CHECKBOX_NAME: (env['build2'].pk,)
        }, follow=True)
        self.assertNotContains(r, 'Devices related to build')
        self.assertContains(r, 'has never upgraded yet')
        self.assertNotContains(r, '<input type="submit" name="upgrade_related"')
        self.assertContains(r, '<input type="submit" name="upgrade_all"')

    def test_upgrade_related(self):
        self._login()
        env = self._create_upgrade_env()
        self._create_firmwareless_device(organization=env['d1'].organization)
        # check state is good before proceeding
        fw = self.device_firmware_model.objects.filter(image__build_id=env['build2'].pk) \
            .select_related('image')
        self.assertEqual(Device.objects.count(), 3)
        self.assertEqual(self.upgrade_operation_model.objects.count(), 0)
        self.assertEqual(fw.count(), 0)
        r = self.client.post(self.BUILD_LIST_URL, {
            'action': 'upgrade_selected',
            'upgrade_related': 'upgrade_related',
            ACTION_CHECKBOX_NAME: (env['build2'].pk,)
        }, follow=True)
        self.assertContains(r, '<li class="success">')
        self.assertContains(r, 'operation started')
        self.assertEqual(self.upgrade_operation_model.objects.count(), 2)
        self.assertEqual(fw.count(), 2)

    def test_upgrade_all(self):
        self._login()
        env = self._create_upgrade_env()
        self._create_firmwareless_device(organization=env['d1'].organization)
        # check state is good before proceeding
        fw = self.device_firmware_model.objects.filter(image__build_id=env['build2'].pk) \
            .select_related('image')
        self.assertEqual(Device.objects.count(), 3)
        self.assertEqual(self.upgrade_operation_model.objects.count(), 0)
        self.assertEqual(fw.count(), 0)
        r = self.client.post(self.BUILD_LIST_URL, {
            'action': 'upgrade_selected',
            'upgrade_all': 'upgrade_all',
            ACTION_CHECKBOX_NAME: (env['build2'].pk,)
        }, follow=True)
        self.assertContains(r, '<li class="success">')
        self.assertContains(r, 'operation started')
        self.assertEqual(self.upgrade_operation_model.objects.count(), 3)
        self.assertEqual(fw.count(), 3)
