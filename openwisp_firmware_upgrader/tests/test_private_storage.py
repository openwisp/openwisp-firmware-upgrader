import swapper
from django.test import TestCase
from django.urls import reverse

from openwisp_users.tests.utils import TestMultitenantAdminMixin

from .base import TestUpgraderMixin

OrganizationUser = swapper.load_model('openwisp_users', 'OrganizationUser')


class TestPrivateStorage(TestUpgraderMixin, TestMultitenantAdminMixin, TestCase):
    def setUp(self):
        # Firmware image is created in the default organization
        self.image = self._create_firmware_image()
        self.default_org = self._get_org('default')
        self.test_org = self._get_org()

    def _download_firmware_assert_status(self, status_code):
        response = self.client.get(
            reverse('serve_private_file', args=[self.image.file])
        )
        self.assertEqual(response.status_code, status_code)

    def test_unauthenticated_user(self):
        self._download_firmware_assert_status(403)

    def test_authenticated_user(self):
        user = self._get_user()
        self.client.force_login(user)
        self._download_firmware_assert_status(403)

    def test_authenticated_user_with_different_organization(self):
        self._create_org_user()
        user = self._get_user()
        self.client.force_login(user)
        self._download_firmware_assert_status(403)

    def test_authenticated_user_with_same_organization(self):
        self._create_org_user(organization=self.test_org)
        user = self._get_user()
        self.client.force_login(user)
        self._download_firmware_assert_status(403)

    def test_staff_user_with_different_organization(self):
        staff_user = self._get_operator()
        self._create_org_user(user=staff_user, organization=self.default_org)
        self.client.force_login(staff_user)
        self._download_firmware_assert_status(403)

    def test_staff_user_with_same_organization(self):
        staff_user = self._get_operator()
        self._create_org_user(user=staff_user, organization=self.test_org)
        self.client.force_login(staff_user)
        self._download_firmware_assert_status(403)

    def test_staff_operator_with_different_organization(self):
        staff_user = self._get_operator()
        self._create_org_user(
            user=staff_user, organization=self.default_org, is_admin=True
        )
        self.client.force_login(staff_user)
        self._download_firmware_assert_status(403)

    def test_staff_operator_with_same_organization(self):
        staff_user = self._get_operator()
        self._create_org_user(
            user=staff_user, organization=self.test_org, is_admin=True
        )
        self.client.force_login(staff_user)
        self._download_firmware_assert_status(200)

    def test_superuser(self):
        user = self._get_admin()
        self.client.force_login(user)
        self._download_firmware_assert_status(200)
