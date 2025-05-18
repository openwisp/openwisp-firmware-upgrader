import swapper
from django.contrib.auth import get_permission_codename
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse

from openwisp_users.tests.utils import TestMultitenantAdminMixin

from ..swapper import load_model
from .base import TestUpgraderMixin

OrganizationUser = swapper.load_model('openwisp_users', 'OrganizationUser')
FirmwareImage = load_model('FirmwareImage')
Group = swapper.load_model('openwisp_users', 'Group')


class TestPrivateStorage(TestUpgraderMixin, TestMultitenantAdminMixin, TestCase):
    def setUp(self):
        # Firmware image is created in the default organization
        self.image = self._create_firmware_image()
        self.default_org = self._get_org("default")
        self.test_org = self._get_org()

    def _download_firmware_assert_status(self, status_code):
        response = self.client.get(
            reverse("serve_private_file", args=[self.image.file])
        )
        self.assertEqual(response.status_code, status_code)

    def test_unauthenticated_user(self):
        self._download_firmware_assert_status(401)

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

    def test_view_permission_check(self):
        staff_user = self._get_operator()
        self.client.force_login(staff_user)
        org = self.image.build.category.organization

        with self.subTest('Test initial access without permissions'):
            self._download_firmware_assert_status(403)

        # Add view permission first
        content_type = ContentType.objects.get_for_model(FirmwareImage)
        perm_codename = get_permission_codename('view', FirmwareImage._meta)
        view_perm = Permission.objects.get(
            content_type=content_type, codename=perm_codename
        )
        staff_user.user_permissions.add(view_perm)

        with self.subTest('Test access with view permission and org admin status'):
            self._create_org_user(user=staff_user, organization=org, is_admin=True)
            self._download_firmware_assert_status(200)

        # Remove org manager status
        org_user = staff_user.openwisp_users_organization.get(
            organization_users__organization=org
        )
        org_user.is_admin = False
        org_user.save()

        # Remove staff status
        staff_user.is_staff = False
        staff_user.save()

        # Restore org manager status
        org_user.is_admin = True
        org_user.save()

        with self.subTest('Test access without staff status'):
            self._download_firmware_assert_status(403)

        # Remove view permission
        staff_user.user_permissions.remove(view_perm)

        with self.subTest('Test access without view permission'):
            self._download_firmware_assert_status(403)
