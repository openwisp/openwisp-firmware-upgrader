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
