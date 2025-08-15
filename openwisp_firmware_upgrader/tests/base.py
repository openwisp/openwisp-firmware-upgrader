import os
from unittest import mock

import swapper
from django.conf import settings
from django.contrib.auth import get_permission_codename
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile

from openwisp_controller.connection.tests.utils import CreateConnectionsMixin

from ..swapper import load_model

Build = load_model("Build")
Category = load_model("Category")
FirmwareImage = load_model("FirmwareImage")
DeviceFirmware = load_model("DeviceFirmware")
DeviceFirmware = load_model("DeviceFirmware")
Credentials = swapper.load_model("connection", "Credentials")
OrganizationUser = swapper.load_model("openwisp_users", "OrganizationUser")


class TestUpgraderMixin(CreateConnectionsMixin):
    FAKE_IMAGE_PATH = os.path.join(settings.PRIVATE_STORAGE_ROOT, "fake-img.bin")
    FAKE_IMAGE_PATH2 = os.path.join(settings.PRIVATE_STORAGE_ROOT, "fake-img2.bin")
    TPLINK_4300_IMAGE = "ath79-generic-tplink_tl-wdr4300-v1-squashfs-sysupgrade.bin"
    TPLINK_4300_IL_IMAGE = (
        "ath79-generic-tplink_tl-wdr4300-v1-il-squashfs-sysupgrade.bin"
    )

    def tearDown(self):
        super().tearDown()
        for fw in FirmwareImage.objects.all():
            fw.delete()

    def _get_build(self, version="0.1", **kwargs):
        opts = {"version": version}
        opts.update(kwargs)
        try:
            return Build.objects.get(**opts)
        except Build.DoesNotExist:
            return self._create_build(**opts)

    def _get_category(self, cat_name="Test Category", **kwargs):
        opts = {"name": cat_name}
        opts.update(kwargs)
        try:
            return Category.objects.get(**opts)
        except Category.DoesNotExist:
            return self._create_category(**opts)

    def _create_category(self, **kwargs):
        opts = dict(name="Test Category")
        opts.update(kwargs)
        if "organization" not in opts:
            opts["organization"] = self._get_org()
        c = Category(**opts)
        c.full_clean()
        c.save()
        return c

    def _create_build(self, **kwargs):
        opts = dict(version="0.1")
        opts.update(kwargs)
        category_opts = {}
        if "organization" in opts:
            category_opts = {"organization": opts.pop("organization")}
        if "category" not in opts:
            opts["category"] = self._get_category(**category_opts)
        b = Build(**opts)
        b.full_clean()
        b.save()
        return b

    def _create_firmware_image(self, **kwargs):
        opts = dict(type=self.TPLINK_4300_IMAGE)
        opts.update(kwargs)
        category_opts = {}
        if "organization" in opts:
            category_opts["organization"] = opts.pop("organization")
        if "build" not in opts:
            opts["build"] = self._get_build(
                category=self._get_category(**category_opts)
            )
        if "file" not in opts:
            opts["file"] = self._get_simpleuploadedfile()
        fw = FirmwareImage(**opts)
        fw.full_clean()
        fw.save()
        return fw

    def _get_simpleuploadedfile(self, filename=None):
        if not filename:
            filename = self.FAKE_IMAGE_PATH
        with open(filename, "rb") as f:
            image = f.read()
        return SimpleUploadedFile(
            name=f"openwrt-{self.TPLINK_4300_IMAGE}",
            content=image,
            content_type="application/octet-stream",
        )

    def _create_device_firmware(self, upgrade=False, device_connection=True, **kwargs):
        opts = dict()
        opts.update(kwargs)
        if "image" not in opts:
            opts["image"] = self._create_firmware_image()
        if "device" not in opts:
            org = opts["image"].build.category.organization
            opts["device"] = self._create_device(organization=org)
            self._create_config(device=opts["device"])
        if device_connection:
            self._create_device_connection(device=opts["device"])
        device_fw = DeviceFirmware(**opts)
        device_fw.full_clean()
        device_fw.save(upgrade=upgrade)
        return device_fw

    def _create_upgrade_env(
        self, device_firmware=True, upgrade_operation=False, **kwargs
    ):
        org = kwargs.pop("organization", self._get_org())
        category = kwargs.pop("category", self._get_category(organization=org))
        build1 = self._create_build(category=category, version="0.1")
        image1a = self._create_firmware_image(build=build1, type=self.TPLINK_4300_IMAGE)
        image1b = self._create_firmware_image(
            build=build1, type=self.TPLINK_4300_IL_IMAGE
        )
        # create devices
        d1 = self._create_device(
            name="device1",
            organization=org,
            mac_address="00:22:bb:33:cc:44",
            model=image1a.boards[0],
        )
        d2 = self._create_device(
            name="device2",
            organization=org,
            mac_address="00:11:bb:22:cc:33",
            model=image1b.boards[0],
        )
        ssh_credentials = self._get_credentials(organization=None)
        self._create_config(device=d1)
        self._create_config(device=d2)
        self._create_device_connection(device=d1, credentials=ssh_credentials)
        self._create_device_connection(device=d2, credentials=ssh_credentials)

        # create a new firmware build
        build2 = self._create_build(category=category, version="0.2")
        image2a = self._create_firmware_image(build=build2, type=self.TPLINK_4300_IMAGE)
        image2b = self._create_firmware_image(
            build=build2, type=self.TPLINK_4300_IL_IMAGE
        )
        data = {
            "build1": build1,
            "build2": build2,
            "d1": d1,
            "d2": d2,
            "image1a": image1a,
            "image1b": image1b,
            "image2a": image2a,
            "image2b": image2b,
        }
        # force create device firmware (optional)
        if device_firmware:
            device_fw1 = self._create_device_firmware(
                device=d1,
                image=image1a,
                upgrade=upgrade_operation,
                device_connection=False,
            )
            device_fw2 = self._create_device_firmware(
                device=d2,
                image=image1b,
                upgrade=upgrade_operation,
                device_connection=False,
            )
            data.update(
                {
                    "device_fw1": device_fw1,
                    "device_fw2": device_fw2,
                }
            )
        return data

    def _create_firmwareless_device(self, organization):
        d = self._create_device(
            name="firmwareless",
            mac_address="01:12:23:44:55:66",
            organization=organization,
        )
        self._create_config(device=d)
        self._create_device_connection(
            device=d, credentials=Credentials.objects.first()
        )
        return d

    def _create_device_with_connection(self, **kwargs):
        d1 = self._create_device(**kwargs)
        self._create_config(device=d1)
        self._create_device_connection(device=d1)
        return d1


def spy_mock(method, pre_action):
    magicmock = mock.MagicMock()

    def wrapper(*args, **kwargs):
        magicmock(*args, **kwargs)
        pre_action(*args, **kwargs)
        return method(*args, **kwargs)

    wrapper.mock = magicmock
    return wrapper


class FirmwareDownloadPermissionTestMixin:
    """
    Mixin for testing firmware download permissions.

    This mixin provides common test methods for both API and private storage
    firmware download tests. The subclass should implement:
    - get_download_url(): return the URL to test
    - expected_queries: class variable dict mapping scenario names to query counts
    """

    expected_queries = {
        "unauthenticated": None,
        "no_permissions": None,
        "authenticated_no_permission": None,
        "different_org": None,
        "staff_no_permissions": None,
        "staff_different_org": None,
        "staff_with_permission": None,
        "operator_same_org": None,
        "superuser": None,
    }

    def setUp(self):
        super().setUp()
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

    def get_download_url(self):
        """Return the URL to test. Must be implemented by subclass."""
        raise NotImplementedError("Subclass must implement get_download_url()")

    def get_expected_queries(self, scenario):
        """
        Return expected query count for scenario.

        Args:
            scenario: str identifier for the test scenario

        Returns:
            int or None: Expected number of database queries for the scenario
        """
        return self.expected_queries.get(scenario)

    def _setup_user(
        self,
        is_staff=False,
        is_org_admin=False,
        org=None,
        has_view_perm=False,
        is_operator=False,
        auto_login=True,
    ):
        """Helper method to setup user with specific permissions"""
        user = self._create_user(is_staff=is_staff)
        if is_org_admin and org:
            self._create_org_user(user=user, organization=org, is_admin=is_org_admin)
        if has_view_perm:
            user.user_permissions.add(self.view_perm)
        if is_operator:
            user.groups.add(self.operator_group)
        if auto_login:
            if hasattr(self, "_login"):
                # For API tests that use TestAPIUpgraderMixin
                self._login(user.username, "tester")
            else:
                # For private storage tests that use force_login
                self.client.force_login(user)
        return user

    def _make_request_and_assert(self, expected_status, scenario, user=None):
        """Make request and assert response status"""
        url = self.get_download_url()
        expected_queries = self.get_expected_queries(scenario)

        if expected_queries is not None:
            with self.assertNumQueries(expected_queries):
                response = self.client.get(url)
        else:
            response = self.client.get(url)

        self.assertEqual(response.status_code, expected_status)
        return response

    def test_firmware_download_unauthenticated_user(self):
        """Test firmware download with unauthenticated user"""
        self.client.logout()
        self.client.defaults = {}
        self._make_request_and_assert(401, "unauthenticated")

    def test_firmware_download_user_without_permissions(self):
        """Test firmware download with user without any permissions"""
        self._setup_user()
        self._make_request_and_assert(403, "no_permissions")

    def test_firmware_download_authenticated_user_without_permission(self):
        """Test firmware download with authenticated user without permission"""
        user = self._get_user()
        if hasattr(self, "_login"):
            self._login(user.username, "tester")
        else:
            self.client.force_login(user)
        self._make_request_and_assert(403, "authenticated_no_permission")

    def test_firmware_download_user_different_organization(self):
        """Test firmware download with user from different organization"""
        self._setup_user(org=self.other_org)
        self._make_request_and_assert(403, "different_org")

    def test_firmware_download_staff_user_without_org_admin_or_view_permission(self):
        """Test firmware download with staff user without org admin or view permission"""
        self._setup_user(is_staff=True)
        self._make_request_and_assert(403, "staff_no_permissions")

    def test_firmware_download_staff_user_org_admin_different_organization(self):
        """Test firmware download with staff user who is org admin of a different organization"""
        self._setup_user(
            is_staff=True,
            is_org_admin=True,
            org=self.other_org,
        )
        self._make_request_and_assert(403, "staff_different_org")

    def test_firmware_download_staff_user_with_view_permission(self):
        """Test firmware download with staff user who has view permission"""
        self._setup_user(
            is_staff=True,
            has_view_perm=True,
            is_operator=True,
        )
        self._make_request_and_assert(403, "staff_with_permission")

    def test_firmware_download_operator_same_organization(self):
        """Test firmware download with operator from same organization"""
        staff_user = self._get_operator()
        # Clear existing relationships and set up properly
        staff_user.user_permissions.clear()
        staff_user.groups.clear()
        OrganizationUser.objects.filter(user=staff_user).delete()

        # Add to Operator group
        staff_user.groups.add(self.operator_group)

        # Create org admin relationship with the image's organization
        self._create_org_user(
            user=staff_user,
            organization=self.image.build.category.organization,
            is_admin=True,
        )

        if hasattr(self, "_login"):
            self._login(staff_user.username, "tester")
        else:
            self.client.force_login(staff_user)

        self._make_request_and_assert(200, "operator_same_org")

    def test_firmware_download_superuser_access(self):
        """Test firmware download with superuser access"""
        user = self._get_admin()
        if hasattr(self, "_login"):
            self._login(user.username, "tester")
        else:
            self.client.force_login(user)

        self._make_request_and_assert(200, "superuser")
