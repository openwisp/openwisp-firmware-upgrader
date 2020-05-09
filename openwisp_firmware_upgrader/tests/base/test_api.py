from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from openwisp_firmware_upgrader.api.serializers import (  # BuildListSerializer,
    BatchUpgradeOperationListSerializer,
    BatchUpgradeOperationSerializer,
    BuildSerializer,
    CategorySerializer,
    FirmwareImageSerializer,
)
from openwisp_firmware_upgrader.tests.base import TestUpgraderMixin
from swapper import load_model

from openwisp_users.models import OrganizationUser
from openwisp_users.tests.utils import TestMultitenantAdminMixin

BatchUpgradeOperation = load_model('firmware_upgrader', 'BatchUpgradeOperation')
Build = load_model('firmware_upgrader', 'Build')
Category = load_model('firmware_upgrader', 'Category')
DeviceFirmware = load_model('firmware_upgrader', 'DeviceFirmware')
FirmwareImage = load_model('firmware_upgrader', 'FirmwareImage')
UpgradeOperation = load_model('firmware_upgrader', 'UpgradeOperation')

user_model = get_user_model()


class TestAPIUpgraderMixin(TestMultitenantAdminMixin, TestUpgraderMixin):
    def setUp(self):
        self.org = self._get_org()
        self.operator = self._create_operator(organizations=[self.org])
        self._login()

    def _obtain_auth_token(self, username='operator', password='tester'):
        params = {'username': username, 'password': password}
        url = reverse('users:user_auth_token')
        r = self.client.post(url, params)
        return r.data["token"]

    def _login(self, username='operator', password='tester'):
        token = self._obtain_auth_token(username, password)
        self.client = Client(HTTP_AUTHORIZATION='Bearer ' + token)


class BaseTestBuildViews(TestAPIUpgraderMixin):
    batch_upgrade_operation_model = BatchUpgradeOperation
    build_model = Build
    category_model = Category
    device_firmware_model = DeviceFirmware
    firmware_image_model = FirmwareImage
    upgrade_operation_model = UpgradeOperation

    def _serialize_build(self, build):
        serializer = BuildSerializer()
        return dict(serializer.to_representation(build))

    def test_build_unauthorized(self):
        build = self._create_build()

        org2 = self._create_org(name='org2', slug='org2')
        self.operator.openwisp_users_organization.all().delete()
        OrganizationUser.objects.create(user=self.operator, organization=org2)

        url = reverse('upgrader:api_build_detail', args=[build.pk])
        r = self.client.get(url)
        self.assertEqual(r.status_code, 404)

        client = Client()
        url = reverse('upgrader:api_build_list')
        r = client.get(url)
        self.assertEqual(r.status_code, 401)
        url = reverse('upgrader:api_build_detail', args=[build.pk])
        r = client.get(url)
        self.assertEqual(r.status_code, 401)

    def test_build_list(self):
        self._create_build(organization=self.org)
        self._create_build(version='0.2', organization=self.org)
        serialized_list = [
            self._serialize_build(build)
            for build in self.build_model.objects.all().order_by('-created')
        ]
        url = reverse('upgrader:api_build_list')
        r = self.client.get(url)
        self.assertEqual(r.data, serialized_list)

    def test_build_list_filter_org(self):
        org2 = self._create_org(name='New org', slug='new-org')
        self._create_operator(
            organizations=[org2], username='operator2', email='operator2@test.com'
        )
        cat2 = self._create_category(name='New category', organization=org2)

        build = self._create_build(organization=self.org)
        build2 = self._create_build(version='0.2', category=cat2)

        url = reverse('upgrader:api_build_list')

        self._login('operator', 'tester')
        serialized_list = [
            self._serialize_build(build),
        ]
        r = self.client.get(url)
        self.assertEqual(r.data, serialized_list)

        self._login('operator2', 'tester')
        serialized_list = [
            self._serialize_build(build2),
        ]
        r = self.client.get(url)
        self.assertEqual(r.data, serialized_list)

    def test_build_list_filter_org_admin(self):
        org2 = self._create_org(name='New org', slug='new-org')
        cat2 = self._create_category(name='New category', organization=org2)
        self._create_operator(
            username='admin', email='admin@test.com', is_superuser=True
        )

        self._create_build(organization=self.org)
        build2 = self._create_build(version='0.2', category=cat2)

        url = reverse('upgrader:api_build_list')

        self._login('admin', 'tester')
        serialized_list = [
            self._serialize_build(build)
            for build in self.build_model.objects.all().order_by('-created')
        ]
        r = self.client.get(url)
        self.assertEqual(r.data, serialized_list)

        data_filter = {"org": "New org"}
        serialized_list = [
            self._serialize_build(build2),
        ]
        r = self.client.get(url, data_filter)
        self.assertEqual(r.data, serialized_list)

    def test_build_create(self):
        category = self._get_category()
        url = reverse('upgrader:api_build_list')
        data = {
            "category": category.pk,
            "version": "asd",
        }
        r = self.client.post(url, data)
        self.assertEqual(self.build_model.objects.count(), 1)
        build = self.build_model.objects.first()
        serialized = self._serialize_build(build)
        self.assertEqual(r.data, serialized)

    def test_build_view(self):
        build = self._create_build()
        serialized = self._serialize_build(build)
        url = reverse('upgrader:api_build_detail', args=[build.pk])
        r = self.client.get(url)
        self.assertEqual(r.data, serialized)

    def test_build_update(self):
        build = self._create_build()
        category = self._get_category()
        url = reverse('upgrader:api_build_detail', args=[build.pk])
        data = {
            "category": str(category.pk),
            "version": "20.04",
            "changelog": "PUT update",
        }
        r = self.client.put(url, data, content_type='application/json')
        self.assertEqual(r.data["id"], str(build.pk))
        self.assertEqual(r.data["category"], build.category.pk)
        self.assertEqual(r.data["version"], "20.04")
        self.assertEqual(r.data["changelog"], "PUT update")

    def test_build_update_partial(self):
        build = self._create_build()
        url = reverse('upgrader:api_build_detail', args=[build.pk])
        data = dict(changelog='PATCH update')
        r = self.client.patch(url, data, content_type='application/json')
        self.assertEqual(r.data["id"], str(build.pk))
        self.assertEqual(r.data["category"], build.category.pk)
        self.assertEqual(r.data["version"], build.version)
        self.assertEqual(r.data["changelog"], "PATCH update")

    def test_build_delete(self):
        build = self._create_build()
        self.assertEqual(self.build_model.objects.count(), 1)
        url = reverse('upgrader:api_build_detail', args=[build.pk])
        r = self.client.delete(url)
        self.assertEqual(r.status_code, 204)
        self.assertEqual(self.build_model.objects.count(), 0)


class BaseTestCategoryViews(TestAPIUpgraderMixin):
    def _serialize_category(self, category):
        serializer = CategorySerializer()
        return dict(serializer.to_representation(category))

    def test_category_unauthorized(self):
        category = self._create_category()

        org2 = self._create_org(name='org2', slug='org2')
        self.operator.openwisp_users_organization.all().delete()
        OrganizationUser.objects.create(user=self.operator, organization=org2)

        url = reverse('upgrader:api_category_detail', args=[category.pk])
        r = self.client.get(url)
        self.assertEqual(r.status_code, 404)

        client = Client()
        url = reverse('upgrader:api_category_list')
        r = client.get(url)
        self.assertEqual(r.status_code, 401)
        url = reverse('upgrader:api_category_detail', args=[category.pk])
        r = client.get(url)
        self.assertEqual(r.status_code, 401)

    def test_category_list(self):
        self._create_category()
        self._create_category(name='New category')
        serialized_list = [
            self._serialize_category(category)
            for category in self.category_model.objects.all().order_by('name')
        ]
        url = reverse('upgrader:api_category_list')
        r = self.client.get(url)
        self.assertEqual(r.data, serialized_list)

    def test_category_list_filter_org(self):
        org2 = self._create_org(name='New org', slug='new-org')
        self._create_operator(
            organizations=[org2], username='operator2', email='operator2@test.com'
        )

        category = self._create_category()
        category2 = self._create_category(name='New category', organization=org2)

        url = reverse('upgrader:api_category_list')

        self._login('operator', 'tester')
        serialized_list = [
            self._serialize_category(category),
        ]
        r = self.client.get(url)
        self.assertEqual(r.data, serialized_list)

        self._login('operator2', 'tester')
        serialized_list = [
            self._serialize_category(category2),
        ]
        r = self.client.get(url)
        self.assertEqual(r.data, serialized_list)

    def test_category_list_filter_org_admin(self):
        org2 = self._create_org(name='New org', slug='new-org')
        self._create_operator(
            username='admin', email='admin@test.com', is_superuser=True
        )

        self._create_category()
        category2 = self._create_category(name='New category', organization=org2)

        url = reverse('upgrader:api_category_list')

        self._login('admin', 'tester')
        serialized_list = [
            self._serialize_category(category)
            for category in self.category_model.objects.all().order_by('name')
        ]
        r = self.client.get(url)
        self.assertEqual(r.data, serialized_list)

        data_filter = {"org": "New org"}
        serialized_list = [
            self._serialize_category(category2),
        ]
        r = self.client.get(url, data_filter)
        self.assertEqual(r.data, serialized_list)

    def test_category_create(self):
        url = reverse('upgrader:api_category_list')
        data = {
            "name": "Dummy category",
            "organization": self.org.pk,
        }
        r = self.client.post(url, data)
        self.assertEqual(self.category_model.objects.count(), 1)
        category = self.category_model.objects.first()
        serialized = self._serialize_category(category)
        self.assertEqual(r.data, serialized)

    def test_category_view(self):
        category = self._get_category()
        serialized = self._serialize_category(category)
        url = reverse('upgrader:api_category_detail', args=[category.pk])
        r = self.client.get(url)
        self.assertEqual(r.data, serialized)

    def test_category_update(self):
        category = self._get_category()
        url = reverse('upgrader:api_category_detail', args=[category.pk])
        data = {
            "name": "New name",
            "organization": category.organization.pk,
        }
        r = self.client.put(url, data, content_type='application/json')
        self.assertEqual(r.data["id"], str(category.pk))
        self.assertEqual(r.data["name"], "New name")
        self.assertEqual(r.data["organization"], category.organization.pk)

    def test_category_update_partial(self):
        category = self._get_category()
        url = reverse('upgrader:api_category_detail', args=[category.pk])
        data = dict(name='New name')
        r = self.client.patch(url, data, content_type='application/json')
        self.assertEqual(r.data["id"], str(category.pk))
        self.assertEqual(r.data["name"], "New name")
        self.assertEqual(r.data["organization"], category.organization.pk)

    def test_category_delete(self):
        category = self._get_category()
        self.assertEqual(self.category_model.objects.count(), 1)
        url = reverse('upgrader:api_category_detail', args=[category.pk])
        r = self.client.delete(url)
        self.assertEqual(r.status_code, 204)
        self.assertEqual(self.category_model.objects.count(), 0)


class BaseTestBatchUpgradeOperationViews(TestAPIUpgraderMixin):
    batch_upgrade_operation_model = BatchUpgradeOperation
    build_model = Build
    category_model = Category
    device_firmware_model = DeviceFirmware
    firmware_image_model = FirmwareImage
    upgrade_operation_model = UpgradeOperation

    def _serialize_upgrade_env(self, upgrade_env, action='list'):
        serializer = {
            'list': BatchUpgradeOperationListSerializer,
            'detail': BatchUpgradeOperationSerializer,
        }[action]()
        return dict(serializer.to_representation(upgrade_env))

    def test_batchupgradeoperation_unauthorized(self):
        env = self._create_upgrade_env()
        env['build2'].batch_upgrade(firmwareless=False)

        org2 = self._create_org(name='org2', slug='org2')
        self.operator.openwisp_users_organization.all().delete()
        OrganizationUser.objects.create(user=self.operator, organization=org2)

        url = reverse(
            'upgrader:api_batchupgradeoperation_detail', args=[env['build2'].pk]
        )
        r = self.client.get(url)
        self.assertEqual(r.status_code, 404)

        client = Client()
        url = reverse('upgrader:api_batchupgradeoperation_list')
        r = client.get(url)
        self.assertEqual(r.status_code, 401)
        url = reverse(
            'upgrader:api_batchupgradeoperation_detail', args=[env['build2'].pk]
        )
        r = client.get(url)
        self.assertEqual(r.status_code, 401)

    def test_batchupgradeoperation_list(self):
        env = self._create_upgrade_env()
        env['build2'].batch_upgrade(firmwareless=False)
        operation = self.batch_upgrade_operation_model.objects.get(build=env['build2'])
        serialized_list = [self._serialize_upgrade_env(operation)]
        url = reverse('upgrader:api_batchupgradeoperation_list')
        r = self.client.get(url)
        self.assertEqual(r.data, serialized_list)

    def test_batchupgradeoperation_list_filter_org(self):
        org2 = self._create_org(name='New org', slug='new-org')
        category2 = self._create_category(name='New category', organization=org2)
        self._create_operator(
            organizations=[org2], username='operator2', email='operator2@test.com'
        )

        env = self._create_upgrade_env(organization=self.org)
        env2 = self._create_upgrade_env(category=category2, organization=org2)
        env['build2'].batch_upgrade(firmwareless=False)
        env2['build2'].batch_upgrade(firmwareless=False)

        url = reverse('upgrader:api_batchupgradeoperation_list')

        self._login('operator', 'tester')
        operation = self.batch_upgrade_operation_model.objects.get(build=env['build2'])
        serialized_list = [self._serialize_upgrade_env(operation)]
        r = self.client.get(url)
        self.assertEqual(r.data, serialized_list)

        self._login('operator2', 'tester')
        operation2 = self.batch_upgrade_operation_model.objects.get(
            build=env2['build2']
        )
        serialized_list = [self._serialize_upgrade_env(operation2)]
        r = self.client.get(url)
        self.assertEqual(r.data, serialized_list)

    def test_batchupgradeoperation_list_filter_org_admin(self):
        org2 = self._create_org(name='New org', slug='new-org')
        category2 = self._create_category(name='New category', organization=org2)
        self._create_operator(
            username='admin', email='admin@test.com', is_superuser=True
        )

        env = self._create_upgrade_env(organization=self.org)
        env2 = self._create_upgrade_env(category=category2, organization=org2)
        env['build2'].batch_upgrade(firmwareless=False)
        env2['build2'].batch_upgrade(firmwareless=False)

        self.batch_upgrade_operation_model.objects.get(build=env['build2'])
        operation2 = self.batch_upgrade_operation_model.objects.get(
            build=env2['build2']
        )

        url = reverse('upgrader:api_batchupgradeoperation_list')

        self._login('admin', 'tester')

        serialized_list = [
            self._serialize_upgrade_env(operation)
            for operation in self.batch_upgrade_operation_model.objects.all().order_by(
                '-created'
            )
        ]
        r = self.client.get(url)
        self.assertEqual(r.data, serialized_list)

        data_filter = {"org": "New org"}
        serialized_list = [self._serialize_upgrade_env(operation2)]
        r = self.client.get(url, data_filter)
        self.assertEqual(r.data, serialized_list)

    def test_batchupgradeoperation_view(self):
        env = self._create_upgrade_env()
        env['build2'].batch_upgrade(firmwareless=False)
        operation = self.batch_upgrade_operation_model.objects.get(build=env['build2'])
        serialized = self._serialize_upgrade_env(operation, action='detail')
        url = reverse('upgrader:api_batchupgradeoperation_detail', args=[operation.pk])
        r = self.client.get(url)
        self.assertEqual(r.data, serialized)


class BaseTestFirmwareImageViews(TestAPIUpgraderMixin):
    batch_upgrade_operation_model = BatchUpgradeOperation
    build_model = Build
    category_model = Category
    device_firmware_model = DeviceFirmware
    firmware_image_model = FirmwareImage
    upgrade_operation_model = UpgradeOperation

    def _serialize_image(self, firmware):
        serializer = FirmwareImageSerializer()
        data = dict(serializer.to_representation(firmware))
        data['file'] = 'http://testserver' + data['file']
        return data

    def test_firmware_unauthorized(self):
        image = self._create_firmware_image()

        org2 = self._create_org(name='org2', slug='org2')
        self.operator.openwisp_users_organization.all().delete()
        OrganizationUser.objects.create(user=self.operator, organization=org2)

        url = reverse('upgrader:api_firmware_detail', args=[image.build.pk, image.pk])
        r = self.client.get(url)
        self.assertEqual(r.status_code, 404)

        url = reverse('upgrader:api_firmware_download', args=[image.build.pk, image.pk])
        r = self.client.get(url)
        self.assertEqual(r.status_code, 404)

        client = Client()
        url = reverse('upgrader:api_firmware_list', args=[image.build.pk])
        r = client.get(url)
        self.assertEqual(r.status_code, 401)
        url = reverse('upgrader:api_firmware_detail', args=[image.build.pk, image.pk])
        r = client.get(url)
        self.assertEqual(r.status_code, 401)
        url = reverse('upgrader:api_firmware_download', args=[image.build.pk, image.pk])
        r = client.get(url)
        self.assertEqual(r.status_code, 401)

    def test_firmware_list(self):
        image = self._create_firmware_image()
        self._create_firmware_image(type=self.TPLINK_4300_IL_IMAGE)

        serialized_list = [
            self._serialize_image(image)
            for image in self.firmware_image_model.objects.all().order_by('-created')
        ]
        url = reverse('upgrader:api_firmware_list', args=[image.build.pk])
        r = self.client.get(url)
        self.assertEqual(r.data, serialized_list)

    def test_firmware_list_filter_org(self):
        org2 = self._create_org(name='New org', slug='new-org')
        self._create_operator(
            organizations=[org2], username='operator2', email='operator2@test.com'
        )
        cat2 = self._create_category(name='New category', organization=org2)

        image = self._create_firmware_image()
        build2 = self._create_build(version='0.2', category=cat2)
        image2 = self._create_firmware_image(build=build2)

        url = reverse('upgrader:api_firmware_list', args=[image.build.pk])

        self._login('operator', 'tester')
        serialized_list = [self._serialize_image(image)]
        r = self.client.get(url)
        self.assertEqual(r.data, serialized_list)

        url = reverse('upgrader:api_firmware_list', args=[image2.build.pk])
        self._login('operator2', 'tester')
        serialized_list = [self._serialize_image(image2)]
        r = self.client.get(url)
        self.assertEqual(r.data, serialized_list)

    def test_firmware_list_filter_org_admin(self):
        org2 = self._create_org(name='New org', slug='new-org')
        self._create_operator(
            username='admin', email='admin@test.com', is_superuser=True
        )
        cat2 = self._create_category(name='New category', organization=org2)

        image = self._create_firmware_image()
        build2 = self._create_build(version='0.2', category=cat2)
        image2 = self._create_firmware_image(build=build2)

        url = reverse('upgrader:api_firmware_list', args=[image.build.pk])

        self._login('admin', 'tester')
        serialized_list = [
            self._serialize_image(image),
        ]

        r = self.client.get(url)
        self.assertEqual(r.data, serialized_list)

        url = reverse('upgrader:api_firmware_list', args=[image2.build.pk])

        data_filter = {"org": "New org"}
        serialized_list = [self._serialize_image(image2)]
        r = self.client.get(url, data_filter)
        self.assertEqual(r.data, serialized_list)

    def test_firmware_create(self):
        build = self._create_build()
        url = reverse('upgrader:api_firmware_list', args=[build.pk])
        data = {
            # It requires a non-empty file to be uploaded
            "file": self._get_simpleuploadedfile(self.FAKE_IMAGE_PATH2),
            "type": self.TPLINK_4300_IMAGE,
        }
        r = self.client.post(url, data)
        self.assertEqual(self.firmware_image_model.objects.count(), 1)
        image = self.firmware_image_model.objects.first()
        serialized = self._serialize_image(image)
        self.assertEqual(r.data, serialized)

    def test_firmware_view(self):
        image = self._create_firmware_image()
        serialized = self._serialize_image(image)
        url = reverse('upgrader:api_firmware_detail', args=[image.build.pk, image.pk])
        r = self.client.get(url)
        self.assertEqual(r.data, serialized)

    # FIXME: I'm unable to get the test working
    """
    def test_firmware_update(self):
        image = self._create_firmware_image()
        url = reverse('upgrader:api_firmware_detail', args=[image.build.pk ,image.pk])
        data = {
            "type": self.TPLINK_4300_IL_IMAGE,
            "file": self._get_simpleuploadedfile_multipart(),
        }
        #r = self.client.put(url, data, content_disposition="attachment;
                             filename=f'openwrt-{self.TPLINK_4300_IMAGE}'")
        r = self.client.put(url, data, content_type='multipart/form-data')
        import ipdb; ipdb.set_trace()
        self.assertEqual(r.data["id"], str(image.pk))
        self.assertEqual(r.data["build"], image.build.pk)
        self.assertEqual(r.data["type"], self.TPLINK_4300_IL_IMAGE)
    """

    def test_firmware_update_partial(self):
        image = self._create_firmware_image()
        url = reverse('upgrader:api_firmware_detail', args=[image.build.pk, image.pk])
        data = dict(type=self.TPLINK_4300_IL_IMAGE)
        r = self.client.patch(url, data, content_type='application/json')
        self.assertEqual(r.data["id"], str(image.pk))
        self.assertEqual(r.data["type"], self.TPLINK_4300_IL_IMAGE)

    def test_firmware_delete(self):
        image = self._create_firmware_image()
        self.assertEqual(self.firmware_image_model.objects.count(), 1)
        url = reverse('upgrader:api_firmware_detail', args=[image.build.pk, image.pk])
        r = self.client.delete(url)
        self.assertEqual(r.status_code, 204)
        self.assertEqual(self.firmware_image_model.objects.count(), 0)

    def test_firmware_download(self):
        image = self._create_firmware_image()
        with open(self.FAKE_IMAGE_PATH, 'rb') as f:
            content = f.read()
        url = reverse('upgrader:api_firmware_download', args=[image.build.pk, image.pk])
        r = self.client.get(url)
        self.assertEqual(r.content, content)
