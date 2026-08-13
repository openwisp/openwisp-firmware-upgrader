import swapper
from django.test import TestCase
from django.urls import reverse

from openwisp_users.tests.utils import TestMultitenantAdminMixin

from .base import FirmwareDownloadPermissionTestMixin, TestUpgraderMixin

OrganizationUser = swapper.load_model("openwisp_users", "OrganizationUser")


class TestPrivateStorage(
    FirmwareDownloadPermissionTestMixin,
    TestUpgraderMixin,
    TestMultitenantAdminMixin,
    TestCase,
):
    expected_queries = {
        "unauthenticated": 0,
        "no_permissions": 3,
        "authenticated_no_permission": 3,
        "different_org": 3,
        "staff_no_permissions": 3,
        "staff_different_org": 3,
        "staff_with_permission": 8,
        "operator_same_org": 7,
        "superuser": 2,
    }

    def get_download_url(self):
        """Return the private storage firmware download URL"""
        return reverse("serve_private_file", args=[self.image.file])

    def test_firmware_download_disabled_organization(self):
        org = self._create_org(name="disabled-download-org")
        administrator = self._create_administrator(organizations=[org])
        admin = self._get_admin()
        image = self._create_firmware_image(organization=org)
        org.is_active = False
        org.save(update_fields=["is_active"])
        url = reverse("serve_private_file", args=[image.file])

        with self.subTest("Disabling org revokes org manager status"):
            self.client.force_login(administrator)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 403)

        with self.subTest("Superuser can download firmware from disabled org"):
            self.client.force_login(admin)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
