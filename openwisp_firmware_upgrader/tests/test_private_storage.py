import swapper
from django.contrib.auth import get_permission_codename
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse

from openwisp_users.tests.utils import TestMultitenantAdminMixin

from ..swapper import load_model
from .base import TestUpgraderMixin

OrganizationUser = swapper.load_model("openwisp_users", "OrganizationUser")
FirmwareImage = load_model("FirmwareImage")
Group = swapper.load_model("openwisp_users", "Group")


class TestPrivateStorage(TestUpgraderMixin, TestMultitenantAdminMixin, TestCase):
    def setUp(self):
        # Firmware image is created in the default organization
        self.image = self._create_firmware_image()
        self.default_org = self._get_org("default")
        self.test_org = self._get_org()
        self.other_org = self._create_org(name="other", slug="other")

        # Get view permission
        content_type = ContentType.objects.get_for_model(FirmwareImage)
        perm_codename = get_permission_codename("view", FirmwareImage._meta)
        self.view_perm = Permission.objects.get(
            content_type=content_type, codename=perm_codename
        )

        # Get Operator group
        self.operator_group = Group.objects.get(name="Operator")

    def _download_firmware_assert_status(self, status_code):
        """Helper method to test firmware download via private storage view"""
        response = self.client.get(
            reverse("serve_private_file", args=[self.image.file])
        )
        self.assertEqual(response.status_code, status_code)

    def _setup_user(
        self,
        is_staff=False,
        is_org_admin=False,
        org=None,
        has_view_perm=False,
        is_operator=False,
    ):
        """Helper method to setup user with specific permissions"""
        user = self._get_operator()
        user.is_staff = is_staff
        user.save()

        if org:
            self._create_org_user(user=user, organization=org, is_admin=is_org_admin)

        if has_view_perm:
            user.user_permissions.add(self.view_perm)

        if is_operator:
            user.groups.add(self.operator_group)

        self.client.force_login(user)
        return user

    def test_firmware_download_permissions(self):
        """
        Test firmware download permissions for different user scenarios.
        """
        with self.subTest("User without any permissions"):
            user = self._get_user()
            self.client.force_login(user)
            self._download_firmware_assert_status(403)

        with self.subTest("Staff user without org admin or view permission"):
            user = self._get_operator()
            user.is_staff = True
            user.save()
            self.client.force_login(user)
            self._download_firmware_assert_status(403)

        with self.subTest("Staff user who is org admin of a different organization"):
            self._setup_user(
                is_staff=True,
                is_org_admin=True,
                org=self.other_org,
            )
            self._download_firmware_assert_status(403)

        with self.subTest("Staff user who is org admin of same organization"):
            self._setup_user(
                is_staff=True,
                is_org_admin=True,
                org=self.image.build.category.organization,
            )
            self._download_firmware_assert_status(200)

        with self.subTest("Superuser access"):
            user = self._get_admin()
            self.client.force_login(user)
            self._download_firmware_assert_status(200)
