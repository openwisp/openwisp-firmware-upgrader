import uuid

import swapper
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from packaging.version import parse as parse_version
from rest_framework import VERSION as REST_FRAMEWORK_VERSION

from openwisp_firmware_upgrader.api.serializers import (
    BatchUpgradeOperationListSerializer,
    BatchUpgradeOperationSerializer,
    BuildSerializer,
    CategorySerializer,
    DeviceFirmwareSerializer,
    DeviceUpgradeOperationSerializer,
    FirmwareImageSerializer,
    UpgradeOperationSerializer,
)
from openwisp_firmware_upgrader.tests.base import TestUpgraderMixin
from openwisp_users.tests.utils import TestMultitenantAdminMixin
from openwisp_utils.tests import AssertNumQueriesSubTestMixin

from ..swapper import load_model

BatchUpgradeOperation = load_model('BatchUpgradeOperation')
Build = load_model('Build')
Category = load_model('Category')
DeviceFirmware = load_model('DeviceFirmware')
FirmwareImage = load_model('FirmwareImage')
UpgradeOperation = load_model('UpgradeOperation')
OrganizationUser = swapper.load_model('openwisp_users', 'OrganizationUser')

user_model = get_user_model()


class TestAPIUpgraderMixin(
    AssertNumQueriesSubTestMixin, TestMultitenantAdminMixin, TestUpgraderMixin
):
    def setUp(self):
        self.org = self._get_org()
        self.operator = self._create_operator(organizations=[self.org])
        self.administrator = self._create_administrator(organizations=[self.org])
        self._login()

    def _obtain_auth_token(self, username='administrator', password='tester'):
        params = {'username': username, 'password': password}
        url = reverse('users:user_auth_token')
        r = self.client.post(url, params)
        self.assertEqual(r.status_code, 200)
        return r.data['token']

    def _login(self, username='administrator', password='tester'):
        token = self._obtain_auth_token(username, password)
        self.client = Client(HTTP_AUTHORIZATION='Bearer ' + token)


class TestBuildViews(TestAPIUpgraderMixin, TestCase):
    def _serialize_build(self, build):
        serializer = BuildSerializer()
        return dict(serializer.to_representation(build))

    def test_build_unauthorized(self):
        build = self._create_build()
        org2 = self._create_org(name='org2', slug='org2')
        OrganizationUser.objects.create(user=self.operator, organization=org2)

        client = Client()
        url = reverse('upgrader:api_build_list')
        with self.subTest(url=url):
            with self.assertNumQueries(0):
                r = client.get(url)
            self.assertEqual(r.status_code, 401)

        url = reverse('upgrader:api_build_detail', args=[build.pk])
        with self.subTest(url=url):
            with self.assertNumQueries(0):
                r = client.get(url)
            self.assertEqual(r.status_code, 401)

    def test_build_list(self):
        self._create_build(organization=self.org)
        self._create_build(version='0.2', organization=self.org)
        serialized_list = [
            self._serialize_build(build)
            for build in Build.objects.all().order_by('-created')
        ]
        url = reverse('upgrader:api_build_list')
        with self.assertNumQueries(5):
            r = self.client.get(url)
        self.assertEqual(r.data['results'], serialized_list)

    def test_build_list_django_filters(self):
        category1 = self._create_category()
        category2 = self._create_category(name='New category')

        build1 = self._create_build(category=category1)
        build2 = self._create_build(version='0.2', category=category2)
        build3 = self._create_build(version='0.2.1', category=category2)
        url = reverse('upgrader:api_build_list')

        filter_params = dict(category=category1.pk)
        with self.assertNumQueries(6):
            r = self.client.get(url, filter_params)
        self.assertEqual(r.data['results'], [self._serialize_build(build1)])

        filter_params = dict(category=category2.pk)
        with self.assertNumQueries(6):
            r = self.client.get(url, filter_params)
        self.assertEqual(
            r.data['results'],
            [self._serialize_build(build3), self._serialize_build(build2)],
        )

        with self.subTest('test version filter'):
            with self.assertNumQueries(5):
                r = self.client.get(url, {'version': '0.2'})
            self.assertEqual(r.data['results'], [self._serialize_build(build2)])

            with self.assertNumQueries(5):
                r = self.client.get(url, {'version': '0.2.1'})
            self.assertEqual(r.data['results'], [self._serialize_build(build3)])

        with self.subTest('test os filter'):
            build1.os = 'abcdefg'
            build1.save(update_fields=('os',))
            build2.os = 'abcdefg-old'
            build2.save(update_fields=('os',))
            with self.assertNumQueries(5):
                r = self.client.get(url, {'os': build1.os})
            self.assertEqual(r.data['results'], [self._serialize_build(build1)])

        with self.subTest('test version, os, category should AND'):
            filter_params.update({'version': '0.2', 'os': 'abcdefg-old'})
            with self.assertNumQueries(6):
                r = self.client.get(url, filter_params)
            self.assertEqual(r.data['results'], [self._serialize_build(build2)])

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
        with self.assertNumQueries(5):
            r = self.client.get(url)
        self.assertEqual(r.data['results'], serialized_list)

        self._login('operator2', 'tester')
        serialized_list = [
            self._serialize_build(build2),
        ]
        with self.assertNumQueries(5):
            r = self.client.get(url)
        self.assertEqual(r.data['results'], serialized_list)

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
            for build in Build.objects.all().order_by('-created')
        ]
        with self.assertNumQueries(3):
            r = self.client.get(url)
        self.assertEqual(r.data['results'], serialized_list)

        data_filter = {'organization': 'new-org'}
        serialized_list = [
            self._serialize_build(build2),
        ]
        with self.assertNumQueries(3):
            r = self.client.get(url, data_filter)
        self.assertEqual(r.data['results'], serialized_list)

    def test_build_list_filter_html(self):
        self._create_build(organization=self.org)
        url = reverse('upgrader:api_build_list')
        r = self.client.get(url, HTTP_ACCEPT='text/html')
        # fails if django_filter is not in INSTALLED_APPS
        self.assertEqual(r.status_code, 200)

    def test_build_create(self):
        category = self._get_category()
        url = reverse('upgrader:api_build_list')
        data = {
            'category': category.pk,
            'version': 'asd',
        }
        with self.assertNumQueries(9):
            r = self.client.post(url, data)
        self.assertEqual(Build.objects.count(), 1)
        build = Build.objects.first()
        serialized = self._serialize_build(build)
        self.assertEqual(r.data, serialized)

    def test_build_view(self):
        build = self._create_build()
        serialized = self._serialize_build(build)
        url = reverse('upgrader:api_build_detail', args=[build.pk])
        with self.assertNumQueries(5):
            r = self.client.get(url)
        self.assertEqual(r.data, serialized)

    def test_build_update(self):
        build = self._create_build()
        category = self._get_category()
        url = reverse('upgrader:api_build_detail', args=[build.pk])
        data = {
            'category': str(category.pk),
            'version': '20.04',
            'changelog': 'PUT update',
        }
        with self.assertNumQueries(10):
            r = self.client.put(url, data, content_type='application/json')
        self.assertEqual(r.data['id'], str(build.pk))
        self.assertEqual(r.data['category'], build.category.pk)
        self.assertEqual(r.data['version'], '20.04')
        self.assertEqual(r.data['changelog'], 'PUT update')

    def test_build_update_partial(self):
        build = self._create_build()
        url = reverse('upgrader:api_build_detail', args=[build.pk])
        data = dict(changelog='PATCH update')
        expected_queries = (
            8 if parse_version(REST_FRAMEWORK_VERSION) >= parse_version('3.15') else 9
        )
        with self.assertNumQueries(expected_queries):
            r = self.client.patch(url, data, content_type='application/json')
        self.assertEqual(r.data['id'], str(build.pk))
        self.assertEqual(r.data['category'], build.category.pk)
        self.assertEqual(r.data['version'], build.version)
        self.assertEqual(r.data['changelog'], 'PATCH update')

    def test_build_delete(self):
        build = self._create_build()
        self.assertEqual(Build.objects.count(), 1)
        url = reverse('upgrader:api_build_detail', args=[build.pk])
        r = self.client.delete(url)
        self.assertEqual(r.status_code, 204)
        self.assertEqual(Build.objects.count(), 0)

    def test_api_batch_upgrade(self):
        build = self._create_build()
        self.assertEqual(BatchUpgradeOperation.objects.count(), 0)
        self.assertEqual(DeviceFirmware.objects.count(), 0)
        with self.subTest('Existing build'):
            url = reverse('upgrader:api_build_batch_upgrade', args=[build.pk])
            with self.assertNumQueries(8):
                r = self.client.post(url)
            self.assertEqual(BatchUpgradeOperation.objects.count(), 1)
            self.assertEqual(DeviceFirmware.objects.count(), 0)
            batch = BatchUpgradeOperation.objects.first()
            self.assertEqual(r.status_code, 201)
            self.assertEqual(r.data, {'batch': str(batch.pk)})

        with self.subTest('Non existing build'):
            url = reverse('upgrader:api_build_batch_upgrade', args=[uuid.uuid4()])
            with self.assertNumQueries(4):
                r = self.client.post(url)
            self.assertEqual(r.status_code, 404)

    def test_build_upgradeable(self):
        env = self._create_upgrade_env()
        self.assertEqual(BatchUpgradeOperation.objects.count(), 0)

        url = reverse('upgrader:api_build_batch_upgrade', args=[env['build2'].pk])
        with self.assertNumQueries(10):
            r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        device_fw_list = [
            str(device_fw.pk)
            for device_fw in DeviceFirmware.objects.all().order_by('-created')
        ]
        self.assertEqual(r.data, {'device_firmwares': device_fw_list, 'devices': []})
        self.assertEqual(BatchUpgradeOperation.objects.count(), 0)

    def test_build_upgradeable_404(self):
        url = reverse('upgrader:api_build_batch_upgrade', args=[uuid.uuid4()])
        with self.assertNumQueries(4):
            r = self.client.get(url)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(BatchUpgradeOperation.objects.count(), 0)


class TestCategoryViews(TestAPIUpgraderMixin, TestCase):
    def _serialize_category(self, category):
        serializer = CategorySerializer()
        return dict(serializer.to_representation(category))

    def test_category_unauthorized(self):
        category = self._create_category()

        org2 = self._create_org(name='org2', slug='org2')
        self.tearDown()
        self.operator.openwisp_users_organization.all().delete()
        OrganizationUser.objects.create(
            user=self.administrator, organization=org2, is_admin=True
        )
        url = reverse('upgrader:api_category_detail', args=[category.pk])
        with self.assertNumQueries(4):
            r = self.client.get(url)
        self.assertEqual(r.status_code, 404)

        client = Client()
        url = reverse('upgrader:api_category_list')
        with self.assertNumQueries(0):
            r = client.get(url)
        self.assertEqual(r.status_code, 401)
        url = reverse('upgrader:api_category_detail', args=[category.pk])
        with self.assertNumQueries(0):
            r = client.get(url)
        self.assertEqual(r.status_code, 401)

    def test_category_list(self):
        self._create_category()
        self._create_category(name='New category')
        serialized_list = [
            self._serialize_category(category)
            for category in Category.objects.all().order_by('-name')
        ]
        url = reverse('upgrader:api_category_list')
        with self.assertNumQueries(5):
            r = self.client.get(url)
        self.assertEqual(r.data['results'], serialized_list)

    def test_category_list_filter_org(self):
        org2 = self._create_org(name='New org', slug='new-org')
        self._create_administrator(
            organizations=[org2],
            username='administrator2',
            email='administrator2@test.com',
        )

        category = self._create_category()
        category2 = self._create_category(name='New category', organization=org2)

        url = reverse('upgrader:api_category_list')

        self._login('administrator', 'tester')
        serialized_list = [
            self._serialize_category(category),
        ]
        with self.assertNumQueries(5):
            r = self.client.get(url)
        self.assertEqual(r.data['results'], serialized_list)

        self._login('administrator2', 'tester')
        serialized_list = [
            self._serialize_category(category2),
        ]
        with self.assertNumQueries(5):
            r = self.client.get(url)
        self.assertEqual(r.data['results'], serialized_list)

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
            for category in Category.objects.all().order_by('-name')
        ]
        with self.assertNumQueries(3):
            r = self.client.get(url)
        self.assertEqual(r.data['results'], serialized_list)

        data_filter = {'organization': 'new-org'}
        serialized_list = [
            self._serialize_category(category2),
        ]
        with self.assertNumQueries(3):
            r = self.client.get(url, data_filter)
        self.assertEqual(r.data['results'], serialized_list)

    def test_category_create(self):
        url = reverse('upgrader:api_category_list')
        data = {
            'name': 'Dummy category',
            'organization': self.org.pk,
        }
        with self.assertNumQueries(9):
            r = self.client.post(url, data)
        self.assertEqual(Category.objects.count(), 1)
        category = Category.objects.first()
        serialized = self._serialize_category(category)
        self.assertEqual(r.data, serialized)

    def test_category_view(self):
        category = self._get_category()
        serialized = self._serialize_category(category)
        url = reverse('upgrader:api_category_detail', args=[category.pk])
        with self.assertNumQueries(5):
            r = self.client.get(url)
        self.assertEqual(r.data, serialized)

    def test_category_update(self):
        category = self._get_category()
        url = reverse('upgrader:api_category_detail', args=[category.pk])
        data = {
            'name': 'New name',
            'organization': category.organization.pk,
        }
        with self.assertNumQueries(10):
            r = self.client.put(url, data, content_type='application/json')
        self.assertEqual(r.data['id'], str(category.pk))
        self.assertEqual(r.data['name'], 'New name')
        self.assertEqual(r.data['organization'], category.organization.pk)

    def test_category_update_partial(self):
        category = self._get_category()
        url = reverse('upgrader:api_category_detail', args=[category.pk])
        data = dict(name='New name')
        with self.assertNumQueries(9):
            r = self.client.patch(url, data, content_type='application/json')
        self.assertEqual(r.data['id'], str(category.pk))
        self.assertEqual(r.data['name'], 'New name')
        self.assertEqual(r.data['organization'], category.organization.pk)

    def test_category_delete(self):
        category = self._get_category()
        self.assertEqual(Category.objects.count(), 1)
        url = reverse('upgrader:api_category_detail', args=[category.pk])
        r = self.client.delete(url)
        self.assertEqual(r.status_code, 204)
        self.assertEqual(Category.objects.count(), 0)


class TestBatchUpgradeOperationViews(TestAPIUpgraderMixin, TestCase):
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
        self.tearDown()
        self.administrator.openwisp_users_organization.all().delete()
        OrganizationUser.objects.create(
            user=self.administrator, organization=org2, is_admin=True
        )

        url = reverse(
            'upgrader:api_batchupgradeoperation_detail', args=[env['build2'].pk]
        )
        with self.assertNumQueries(4):
            r = self.client.get(url)
        self.assertEqual(r.status_code, 404)

        client = Client()
        url = reverse('upgrader:api_batchupgradeoperation_list')
        with self.assertNumQueries(0):
            r = client.get(url)
        self.assertEqual(r.status_code, 401)
        url = reverse(
            'upgrader:api_batchupgradeoperation_detail', args=[env['build2'].pk]
        )
        with self.assertNumQueries(0):
            r = client.get(url)
        self.assertEqual(r.status_code, 401)

    def test_batchupgradeoperation_list(self):
        env = self._create_upgrade_env()
        env['build2'].batch_upgrade(firmwareless=False)
        operation = BatchUpgradeOperation.objects.get(build=env['build2'])
        serialized_list = [self._serialize_upgrade_env(operation)]
        url = reverse('upgrader:api_batchupgradeoperation_list')
        with self.assertNumQueries(5):
            r = self.client.get(url)
        self.assertEqual(r.data['results'], serialized_list)

    def test_batchupgradeoperation_list_django_filters(self):
        env = self._create_upgrade_env(organization=self.org)
        env['build1'].batch_upgrade(firmwareless=False)
        env['build2'].batch_upgrade(firmwareless=False)

        url = reverse('upgrader:api_batchupgradeoperation_list')

        serialized_list = [
            self._serialize_upgrade_env(operation)
            for operation in BatchUpgradeOperation.objects.order_by('-created')
        ]
        with self.assertNumQueries(5):
            r = self.client.get(url)
        self.assertEqual(r.data['results'], serialized_list)

        operation = BatchUpgradeOperation.objects.get(build=env['build1'])
        serialized_list = [self._serialize_upgrade_env(operation)]
        filter_params = dict(build=env['build1'].pk)
        with self.assertNumQueries(6):
            r = self.client.get(url, filter_params)
        self.assertEqual(r.data['results'], serialized_list)

        operation = BatchUpgradeOperation.objects.get(build=env['build2'])
        serialized_list = [self._serialize_upgrade_env(operation)]
        filter_params = dict(build=env['build2'].pk)
        with self.assertNumQueries(6):
            r = self.client.get(url, filter_params)
        self.assertEqual(r.data['results'], serialized_list)

        serialized_list = [
            self._serialize_upgrade_env(operation)
            for operation in BatchUpgradeOperation.objects.filter(
                status='in-progress'
            ).order_by('-created')
        ]
        filter_params = dict(status='in-progress')
        with self.assertNumQueries(4):
            r = self.client.get(url, filter_params)
        self.assertEqual(r.data['results'], serialized_list)

        serialized_list = [
            self._serialize_upgrade_env(operation)
            for operation in BatchUpgradeOperation.objects.filter(
                status='success'
            ).order_by('-created')
        ]
        filter_params = dict(status='success')
        with self.assertNumQueries(4):
            r = self.client.get(url, filter_params)
        self.assertEqual(r.data['results'], serialized_list)

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
        operation = BatchUpgradeOperation.objects.get(build=env['build2'])
        serialized_list = [self._serialize_upgrade_env(operation)]
        with self.assertNumQueries(5):
            r = self.client.get(url)
        self.assertEqual(r.data['results'], serialized_list)

        self._login('operator2', 'tester')
        operation2 = BatchUpgradeOperation.objects.get(build=env2['build2'])
        serialized_list = [self._serialize_upgrade_env(operation2)]
        with self.assertNumQueries(5):
            r = self.client.get(url)
        self.assertEqual(r.data['results'], serialized_list)

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

        BatchUpgradeOperation.objects.get(build=env['build2'])
        operation2 = BatchUpgradeOperation.objects.get(build=env2['build2'])

        url = reverse('upgrader:api_batchupgradeoperation_list')

        self._login('admin', 'tester')

        serialized_list = [
            self._serialize_upgrade_env(operation)
            for operation in BatchUpgradeOperation.objects.all().order_by('-created')
        ]
        with self.assertNumQueries(3):
            r = self.client.get(url)
        self.assertEqual(r.data['results'], serialized_list)

        data_filter = {'organization': 'new-org'}
        serialized_list = [self._serialize_upgrade_env(operation2)]
        with self.assertNumQueries(3):
            r = self.client.get(url, data_filter)
        self.assertEqual(r.data['results'], serialized_list)

    def test_batchupgradeoperation_view(self):
        env = self._create_upgrade_env()
        env['build2'].batch_upgrade(firmwareless=False)
        operation = BatchUpgradeOperation.objects.get(build=env['build2'])
        serialized = self._serialize_upgrade_env(operation, action='detail')
        url = reverse('upgrader:api_batchupgradeoperation_detail', args=[operation.pk])
        with self.assertNumQueries(7):
            r = self.client.get(url)
        self.assertEqual(r.data, serialized)


class TestFirmwareImageViews(TestAPIUpgraderMixin, TestCase):
    def _serialize_image(self, firmware):
        serializer = FirmwareImageSerializer()
        data = dict(serializer.to_representation(firmware))
        data['file'] = 'http://testserver' + data['file']
        return data

    def test_firmware_unauthorized(self):
        image = self._create_firmware_image()
        org2 = self._create_org(name='org2', slug='org2')
        OrganizationUser.objects.create(user=self.operator, organization=org2)

        client = Client()
        url = reverse('upgrader:api_firmware_list', args=[image.build.pk])
        with self.subTest(url=url):
            with self.assertNumQueries(1):
                r = client.get(url)
            self.assertEqual(r.status_code, 401)

        url = reverse('upgrader:api_firmware_detail', args=[image.build.pk, image.pk])
        with self.subTest(url=url):
            with self.assertNumQueries(1):
                r = client.get(url)
            self.assertEqual(r.status_code, 401)

        url = reverse('upgrader:api_firmware_download', args=[image.build.pk, image.pk])
        with self.subTest(url=url):
            with self.assertNumQueries(1):
                r = client.get(url)
            self.assertEqual(r.status_code, 401)

    def test_firmware_list(self):
        image = self._create_firmware_image()
        self._create_firmware_image(type=self.TPLINK_4300_IL_IMAGE)

        serialized_list = [
            self._serialize_image(image)
            for image in FirmwareImage.objects.all().order_by('-created')
        ]
        url = reverse('upgrader:api_firmware_list', args=[image.build.pk])
        with self.assertNumQueries(6):
            r = self.client.get(url)
        self.assertEqual(r.data['results'], serialized_list)

    def test_firmware_list_404(self):
        pk = uuid.uuid4()
        url = reverse('upgrader:api_firmware_list', args=[pk])
        r = self.client.get(url)
        with self.subTest(pk=pk):
            self.assertEqual(r.status_code, 404)

    def test_firmware_list_django_filters(self):
        image = self._create_firmware_image(type=self.TPLINK_4300_IMAGE)
        image2 = self._create_firmware_image(type=self.TPLINK_4300_IL_IMAGE)

        url = reverse('upgrader:api_firmware_list', args=[image.build.pk])

        filter_params = dict(type=self.TPLINK_4300_IMAGE)
        with self.assertNumQueries(6):
            r = self.client.get(url, filter_params)
        self.assertEqual(r.data['results'], [self._serialize_image(image)])

        url = reverse('upgrader:api_firmware_list', args=[image.build.pk])

        filter_params = dict(type=self.TPLINK_4300_IL_IMAGE)
        with self.assertNumQueries(6):
            r = self.client.get(url, filter_params)
        self.assertEqual(r.data['results'], [self._serialize_image(image2)])

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
        with self.assertNumQueries(6):
            r = self.client.get(url)
        self.assertEqual(r.data['results'], serialized_list)

        url = reverse('upgrader:api_firmware_list', args=[image2.build.pk])
        self._login('operator2', 'tester')
        serialized_list = [self._serialize_image(image2)]
        with self.assertNumQueries(6):
            r = self.client.get(url)
        self.assertEqual(r.data['results'], serialized_list)

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

        with self.assertNumQueries(4):
            r = self.client.get(url)
        self.assertEqual(r.data['results'], serialized_list)

        url = reverse('upgrader:api_firmware_list', args=[image2.build.pk])

        data_filter = {'org': 'New org'}
        serialized_list = [self._serialize_image(image2)]
        with self.assertNumQueries(4):
            r = self.client.get(url, data_filter)
        self.assertEqual(r.data['results'], serialized_list)

    def test_firmware_create(self):
        build = self._create_build()
        url = reverse('upgrader:api_firmware_list', args=[build.pk])
        data = {
            # It requires a non-empty file to be uploaded
            'file': self._get_simpleuploadedfile(self.FAKE_IMAGE_PATH2),
            'type': self.TPLINK_4300_IMAGE,
        }
        with self.assertNumQueries(9):
            r = self.client.post(url, data)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(FirmwareImage.objects.count(), 1)
        image = FirmwareImage.objects.first()
        serialized = self._serialize_image(image)
        self.assertEqual(r.data, serialized)

    def test_firmware_create_404(self):
        pk = uuid.uuid4()
        url = reverse('upgrader:api_firmware_list', args=[pk])
        r = self.client.post(
            url,
            {
                'file': self._get_simpleuploadedfile(self.FAKE_IMAGE_PATH2),
                'type': self.TPLINK_4300_IMAGE,
            },
        )
        with self.subTest(pk=pk):
            self.assertEqual(r.status_code, 404)

    def test_firmware_view(self):
        image = self._create_firmware_image()
        serialized = self._serialize_image(image)
        url = reverse('upgrader:api_firmware_detail', args=[image.build.pk, image.pk])
        with self.assertNumQueries(8):
            r = self.client.get(url)
        self.assertEqual(r.data, serialized)

    def test_firmware_delete(self):
        image = self._create_firmware_image()
        self.assertEqual(FirmwareImage.objects.count(), 1)
        url = reverse('upgrader:api_firmware_detail', args=[image.build.pk, image.pk])
        with self.assertNumQueries(11):
            r = self.client.delete(url)
        self.assertEqual(r.status_code, 204)
        self.assertEqual(FirmwareImage.objects.count(), 0)

    def test_firmware_download(self):
        image = self._create_firmware_image()
        with open(self.FAKE_IMAGE_PATH, 'rb') as f:
            content = f.read()
        url = reverse('upgrader:api_firmware_download', args=[image.build.pk, image.pk])
        with self.subTest("Test as operator"):
            self._login('operator', 'tester')
            with self.assertNumQueries(8):
                response = self.client.get(url)
            self.assertEqual(response.getvalue(), content)
        with self.subTest("Test as superuser"):
            self._get_admin()
            self._login('admin', 'tester')
            with self.assertNumQueries(3):
                response = self.client.get(url)
            self.assertEqual(response.getvalue(), content)

    def test_firmware_no_update(self):
        image = self._create_firmware_image()
        url = reverse('upgrader:api_firmware_detail', args=[image.build.pk, image.pk])
        data = {
            'type': self.TPLINK_4300_IL_IMAGE,
            'file': self._get_simpleuploadedfile(),
        }
        r = self.client.put(url, data, content_type='multipart/form-data')
        self.assertEqual(r.status_code, 405)

    def test_firmware_no_update_partial(self):
        image = self._create_firmware_image()
        url = reverse('upgrader:api_firmware_detail', args=[image.build.pk, image.pk])
        data = dict(type=self.TPLINK_4300_IL_IMAGE)
        r = self.client.patch(url, data, content_type='application/json')
        self.assertEqual(r.status_code, 405)


class TestDeviceFirmwareImageViews(TestAPIUpgraderMixin, TestCase):
    def _serialize_device_firmware(self, device_fw):
        serializer = DeviceFirmwareSerializer()
        return dict(serializer.to_representation(device_fw))

    def _create_device_firmware_multi_env(self):
        org1 = self._get_org()
        org2 = self._create_org(name='New org', slug='new-org')
        cat2 = self._create_category(name='New category2', organization=org2)
        build1 = self._get_build()
        build2 = self._create_build(version='0.2', category=cat2)
        image1 = self._create_firmware_image(build=build1)
        image2 = self._create_firmware_image(build=build2)
        d1 = self._create_device(
            name='device1',
            organization=org1,
            mac_address='00:22:bb:33:cc:44',
            model=image1.boards[0],
        )
        d2 = self._create_device(
            name='device2',
            organization=org2,
            mac_address='00:11:bb:22:cc:33',
            model=image2.boards[0],
        )
        ssh_credentials1 = self._get_credentials(organization=org1)
        ssh_credentials2 = self._get_credentials(organization=org2)
        self._create_config(device=d1)
        self._create_config(device=d2)
        self._create_device_connection(device=d1, credentials=ssh_credentials1)
        self._create_device_connection(device=d2, credentials=ssh_credentials2)
        device_fw1 = self._create_device_firmware(
            device=d1, image=image1, device_connection=False
        )
        device_fw2 = self._create_device_firmware(
            device=d2, image=image2, device_connection=False
        )
        self._create_operator(
            organizations=[org1],
            username='org1_manager',
            email='orgmanager@test.com',
        )
        self._create_operator(username='org1_member', email='orgmember@test.com')
        self._create_operator(
            username='org_admin', email='org_admin@test.com', is_superuser=True
        )
        return d1, d2, image1, image2, device_fw1, device_fw2

    def test_device_firmware_detail_unauthorized(self):
        device_fw = self._create_device_firmware()
        client = Client()
        org2 = self._create_org(name='org2', slug='org2')
        OrganizationUser.objects.create(user=self.operator, organization=org2)
        url = reverse('upgrader:api_devicefirmware_detail', args=[device_fw.device.pk])
        with self.subTest(url=url):
            with self.assertNumQueries(0):
                r = client.get(url)
            self.assertEqual(r.status_code, 401)

    def test_device_firmware_detail_404(self):
        device_pk = uuid.uuid4()
        url = reverse('upgrader:api_devicefirmware_detail', args=[device_pk])
        with self.assertNumQueries(4):
            r = self.client.get(url)
        self.assertEqual(r.status_code, 404)

    def test_device_firmware_detail_400(self):
        env = self._create_upgrade_env()
        device1 = env['d1']
        device2 = env['d2']
        image1a = env['image1a']
        device1.model = 'test model'
        device1.full_clean()
        device1.save()

        with self.subTest('Test device and image model validation'):
            url = reverse('upgrader:api_devicefirmware_detail', args=[device1.pk])
            with self.assertNumQueries(18):
                # Try to make a request when the
                # device model does not match the image model
                data = {'image': image1a.pk}
                r = self.client.put(url, data, content_type='application/json')
            self.assertEqual(r.status_code, 400)
            err = 'Device model and image model do not match'
            self.assertIn(err, r.json()['__all__'][0])

        with self.subTest('Test image pk validation'):
            url = reverse('upgrader:api_devicefirmware_detail', args=[device2.pk])
            with self.assertNumQueries(8):
                # image with different "type"
                data = {'image': image1a.pk}
                r = self.client.put(url, data, content_type='application/json')
            self.assertEqual(r.status_code, 400)
            self.assertIn('Invalid pk', r.json()['image'][0])

    def test_deactivated_device(self):
        device_fw = self._create_device_firmware()
        device_fw.device.deactivate()
        url = reverse('upgrader:api_devicefirmware_detail', args=[device_fw.device.pk])

        with self.subTest('Test retrieving DeviceFirmwareImage'):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)

        with self.subTest('Test updating DeviceFirmwareImage'):
            response = self.client.put(
                url,
                data={'image': device_fw.image.pk},
                content_type='application/json',
            )
            self.assertEqual(response.status_code, 403)

        with self.subTest('Test deleting DeviceFirmwareImage'):
            response = self.client.delete(url)
            self.assertEqual(response.status_code, 403)

    def test_device_firmware_detail_delete(self):
        device_fw = self._create_device_firmware()
        self.assertEqual(DeviceFirmware.objects.count(), 1)
        url = reverse('upgrader:api_devicefirmware_detail', args=[device_fw.device.pk])
        r = self.client.delete(url)
        self.assertEqual(r.status_code, 204)
        self.assertEqual(DeviceFirmware.objects.count(), 0)

    def test_device_firmware_detail_get(self):
        env = self._create_upgrade_env()
        device1 = env['d1']
        image1a = env['image1a']
        image1b = env['image1b']
        image2a = env['image2a']
        image2b = env['image2b']
        device_fw1 = env['device_fw1']
        category2 = self._get_category(
            organization=self._get_org(), cat_name='Test Category2'
        )
        build2 = self._create_build(category=category2, version='0.2')
        image2 = self._create_firmware_image(build=build2, type=self.TPLINK_4300_IMAGE)

        with self.subTest('Test when device firmware exists'):
            url = reverse(
                'upgrader:api_devicefirmware_detail', args=[device_fw1.device.pk]
            )
            with self.assertNumQueries(9):
                r = self.client.get(url, {'format': 'api'})
            self.assertEqual(r.status_code, 200)
            serializer_detail = self._serialize_device_firmware(device_fw1)
            self.assertEqual(r.data, serializer_detail)
            self.assertContains(r, f'{image1a}</option>')
            self.assertContains(r, f'{image2a}</option>')
            # The "image" field in the browsable API only
            # shows images that are available to the device.
            # This behavior is similar to the "device firmware"
            # inline in the admin interface.
            self.assertNotContains(r, f'{image1b}</option>')
            self.assertNotContains(r, f'{image2b}</option>')
            self.assertNotContains(r, f'{image2}</option>')

        with self.subTest('Test when device firmware does not exist'):
            DeviceFirmware.objects.all().delete()
            url = reverse('upgrader:api_devicefirmware_detail', args=[device1.pk])
            with self.assertNumQueries(8):
                r = self.client.get(url, {'format': 'api'})
            self.assertEqual(r.status_code, 404)
            repsonse = r.content.decode()
            self.assertIn(f'{image1a}</option>', repsonse)
            self.assertIn(f'{image2a}</option>', repsonse)
            self.assertIn(f'{image2}</option>', repsonse)
            # The "image" field in the browsable API only
            # shows images that are available to the device.
            # This behavior is similar to the "device firmware"
            # inline in the admin interface.
            self.assertNotIn(f'{image1b}</option>', repsonse)
            self.assertNotIn(f'{image2b}</option>', repsonse)

    def test_device_firmware_detail_create(self):
        env = self._create_upgrade_env(device_firmware=False)
        device1 = env['d1']
        image1a = env['image1a']
        image1b = env['image1b']
        image2a = env['image2a']
        image2b = env['image2b']
        category2 = self._get_category(
            organization=self._get_org(), cat_name='Test Category2'
        )
        build2 = self._create_build(category=category2, version='0.2')
        image2 = self._create_firmware_image(build=build2, type=self.TPLINK_4300_IMAGE)
        url = reverse('upgrader:api_devicefirmware_detail', args=[device1.pk])
        self.assertEqual(DeviceFirmware.objects.count(), 0)
        self.assertEqual(UpgradeOperation.objects.count(), 0)

        with self.assertNumQueries(26):
            data = {'image': image1a.pk}
            # This API view allows the creation
            # of new devicefirmware objects with
            # a PUT request when the object
            # doesn't already exist.
            r = self.client.put(
                f'{url}?format=api', data, content_type='application/json'
            )

        self.assertEqual(r.status_code, 201)
        self.assertEqual(DeviceFirmware.objects.count(), 1)
        self.assertEqual(UpgradeOperation.objects.count(), 1)
        device_fw1 = DeviceFirmware.objects.first()
        uo1 = UpgradeOperation.objects.first()
        serializer_detail = self._serialize_device_firmware(device_fw1)
        serializer_detail.update({'upgrade_operation': {'id': uo1.id}})
        self.assertEqual(r.data, serializer_detail)
        repsonse = r.content.decode()
        self.assertIn(f'{image1a}</option>', repsonse)
        self.assertIn(f'{image2a}</option>', repsonse)
        self.assertNotIn(f'{image1b}</option>', repsonse)
        self.assertNotIn(f'{image2b}</option>', repsonse)
        self.assertNotIn(f'{image2}</option>', repsonse)

    def test_device_firmware_detail_update(self):
        env = self._create_upgrade_env()
        image1a = env['image1a']
        image1b = env['image1b']
        image2a = env['image2a']
        image2b = env['image2b']
        device_fw1 = env['device_fw1']
        category2 = self._get_category(
            organization=self._get_org(), cat_name='Test Category2'
        )
        build2 = self._create_build(category=category2, version='0.2')
        image2 = self._create_firmware_image(build=build2, type=self.TPLINK_4300_IMAGE)
        url = reverse('upgrader:api_devicefirmware_detail', args=[device_fw1.device.pk])
        self.assertEqual(device_fw1.image.pk, image1a.pk)
        self.assertEqual(DeviceFirmware.objects.count(), 2)
        self.assertEqual(UpgradeOperation.objects.count(), 0)

        with self.assertNumQueries(27):
            data = {'image': image2a.pk}
            r = self.client.put(
                f'{url}?format=api', data, content_type='application/json'
            )

        device_fw1.refresh_from_db()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(device_fw1.image.pk, image2a.pk)
        self.assertEqual(DeviceFirmware.objects.count(), 2)
        self.assertEqual(UpgradeOperation.objects.count(), 1)
        uo1 = UpgradeOperation.objects.first()
        serializer_detail = self._serialize_device_firmware(device_fw1)
        serializer_detail.update({'upgrade_operation': {'id': uo1.id}})
        self.assertEqual(r.data, serializer_detail)
        repsonse = r.content.decode()
        self.assertIn(f'{image1a}</option>', repsonse)
        self.assertIn(f'{image2a}</option>', repsonse)
        self.assertNotIn(f'{image1b}</option>', repsonse)
        self.assertNotIn(f'{image2b}</option>', repsonse)
        self.assertNotIn(f'{image2}</option>', repsonse)

    def test_device_firmware_detail_partial_update(self):
        env = self._create_upgrade_env()
        image1a = env['image1a']
        image1b = env['image1b']
        image2a = env['image2a']
        image2b = env['image2b']
        device_fw1 = env['device_fw1']
        category2 = self._get_category(
            organization=self._get_org(), cat_name='Test Category2'
        )
        build2 = self._create_build(category=category2, version='0.2')
        image2 = self._create_firmware_image(build=build2, type=self.TPLINK_4300_IMAGE)
        url = reverse('upgrader:api_devicefirmware_detail', args=[device_fw1.device.pk])
        self.assertEqual(device_fw1.image.pk, image1a.pk)
        self.assertEqual(DeviceFirmware.objects.count(), 2)
        self.assertEqual(UpgradeOperation.objects.count(), 0)

        with self.assertNumQueries(27):
            data = {'image': image2a.pk}
            r = self.client.patch(
                f'{url}?format=api', data, content_type='application/json'
            )

        device_fw1.refresh_from_db()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(device_fw1.image.pk, image2a.pk)
        self.assertEqual(DeviceFirmware.objects.count(), 2)
        self.assertEqual(UpgradeOperation.objects.count(), 1)
        uo1 = UpgradeOperation.objects.first()
        serializer_detail = self._serialize_device_firmware(device_fw1)
        serializer_detail.update({'upgrade_operation': {'id': uo1.id}})
        self.assertEqual(r.data, serializer_detail)
        repsonse = r.content.decode()
        self.assertIn(f'{image1a}</option>', repsonse)
        self.assertIn(f'{image2a}</option>', repsonse)
        self.assertNotIn(f'{image1b}</option>', repsonse)
        self.assertNotIn(f'{image2b}</option>', repsonse)
        self.assertNotIn(f'{image2}</option>', repsonse)

    def test_device_firmware_detail_multitenancy(self):
        (
            d1,
            d2,
            image1,
            image2,
            device_fw1,
            device_fw2,
        ) = self._create_device_firmware_multi_env()

        with self.subTest('Test device firmware detail org manager'):
            self._login('org1_manager', 'tester')
            url = reverse('upgrader:api_devicefirmware_detail', args=[d1.pk])
            with self.assertNumQueries(7):
                r = self.client.get(url, {'format': 'api'})
            self.assertEqual(r.status_code, 200)
            serializer_detail = self._serialize_device_firmware(device_fw1)
            self.assertEqual(r.data, serializer_detail)
            # The 'org1_manager' user is only
            # authorized to view firmware objects
            self.assertNotContains(r, f'{image1}</option>')
            self.assertNotContains(r, f'{image2}</option>')
            # Only device firmware objects belonging to the
            # same organization as org1_manager can be accessed
            url = reverse('upgrader:api_devicefirmware_detail', args=[d2.pk])
            with self.assertNumQueries(4):
                r = self.client.get(url)
            self.assertEqual(r.status_code, 404)

        with self.subTest('Test device firmware detail org member (403 forbidden)'):
            self._login('org1_member', 'tester')
            url = reverse('upgrader:api_devicefirmware_detail', args=[d1.pk])
            err = 'User is not a manager of the organization'
            with self.assertNumQueries(1):
                r = self.client.get(url)
            self.assertEqual(r.status_code, 403)
            self.assertIn(err, r.json()['detail'])
            url = reverse('upgrader:api_devicefirmware_detail', args=[d2.pk])
            with self.assertNumQueries(1):
                r = self.client.get(url)
            self.assertEqual(r.status_code, 403)
            self.assertIn(err, r.json()['detail'])

        with self.subTest('Test device firmware detail org admin'):
            self._login('org_admin', 'tester')
            url = reverse('upgrader:api_devicefirmware_detail', args=[d1.pk])
            with self.assertNumQueries(6):
                r = self.client.get(url, {'format': 'api'})
            self.assertEqual(r.status_code, 200)
            serializer_detail = self._serialize_device_firmware(device_fw1)
            self.assertEqual(r.data, serializer_detail)
            self.assertContains(r, f'{image1}</option>')
            self.assertNotContains(r, f'{image2}</option>')
            url = reverse('upgrader:api_devicefirmware_detail', args=[d2.pk])
            with self.assertNumQueries(6):
                r = self.client.get(url, {'format': 'api'})
            self.assertEqual(r.status_code, 200)
            serializer_detail = self._serialize_device_firmware(device_fw2)
            self.assertEqual(r.data, serializer_detail)
            self.assertContains(r, f'{image2}</option>')
            self.assertNotContains(r, f'{image1}</option>')


class TestDeviceUpgradeOperationViews(TestAPIUpgraderMixin, TestCase):
    def _serialize_device_upgrade_operation(self, device_uo):
        serializer = DeviceUpgradeOperationSerializer()
        return dict(serializer.to_representation(device_uo))

    def _create_device_uo_multi_env(self):
        org1 = self._get_org()
        org2 = self._create_org(name='New org', slug='new-org')
        cat2 = self._create_category(name='New category2', organization=org2)
        build1 = self._get_build()
        build2 = self._create_build(version='0.2', category=cat2)
        image1 = self._create_firmware_image(build=build1)
        image2 = self._create_firmware_image(build=build2)
        d1 = self._create_device(
            name='device1',
            organization=org1,
            mac_address='00:22:bb:33:cc:44',
            model=image1.boards[0],
        )
        d2 = self._create_device(
            name='device2',
            organization=org2,
            mac_address='00:11:bb:22:cc:33',
            model=image2.boards[0],
        )
        ssh_credentials1 = self._get_credentials(organization=org1)
        ssh_credentials2 = self._get_credentials(organization=org2)
        self._create_config(device=d1)
        self._create_config(device=d2)
        self._create_device_connection(device=d1, credentials=ssh_credentials1)
        self._create_device_connection(device=d2, credentials=ssh_credentials2)
        self._create_device_firmware(
            device=d1, image=image1, upgrade=True, device_connection=False
        )
        self._create_device_firmware(
            device=d2, image=image2, upgrade=True, device_connection=False
        )
        self.assertEqual(UpgradeOperation.objects.count(), 2)
        device_uo1 = UpgradeOperation.objects.get(device=d1)
        device_uo2 = UpgradeOperation.objects.get(device=d2)
        self._create_operator(
            organizations=[org1],
            username='org1_manager',
            email='orgmanager@test.com',
        )
        self._create_operator(username='org1_member', email='orgmember@test.com')
        self._create_operator(
            username='org_admin', email='org_admin@test.com', is_superuser=True
        )
        return d1, d2, device_uo1, device_uo2

    def test_device_uo_list_unauthorized(self):
        device_fw = self._create_device_firmware(upgrade=True)
        client = Client()
        org2 = self._create_org(name='org2', slug='org2')
        OrganizationUser.objects.create(user=self.operator, organization=org2)
        url = reverse(
            'upgrader:api_deviceupgradeoperation_list', args=[device_fw.device.pk]
        )
        with self.subTest(url=url):
            with self.assertNumQueries(1):
                r = client.get(url)
            self.assertEqual(r.status_code, 401)

    def test_device_uo_list_404(self):
        device_pk = uuid.uuid4()
        url = reverse('upgrader:api_deviceupgradeoperation_list', args=[device_pk])
        with self.assertNumQueries(1):
            r = self.client.get(url)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json(), {'detail': 'device not found'})

    def test_device_uo_list_get(self):
        env = self._create_upgrade_env(upgrade_operation=True)
        device1 = env['d1']
        self.assertEqual(UpgradeOperation.objects.count(), 2)
        device_uo1 = UpgradeOperation.objects.get(device=device1)

        with self.subTest('Test when device upgrade operations exist'):
            url = reverse('upgrader:api_deviceupgradeoperation_list', args=[device1.pk])
            with self.assertNumQueries(6):
                r = self.client.get(url)
            self.assertEqual(r.status_code, 200)
            serializer_list = self._serialize_device_upgrade_operation(device_uo1)
            self.assertEqual(r.data['results'], [serializer_list])

        with self.subTest('Test when device upgrade operations does not exist'):
            UpgradeOperation.objects.all().delete()
            url = reverse('upgrader:api_deviceupgradeoperation_list', args=[device1.pk])
            with self.assertNumQueries(5):
                r = self.client.get(url)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.data['results'], [])

    def test_device_uo_list_django_filters(self):
        env = self._create_upgrade_env(upgrade_operation=True)
        device1 = env['d1']
        self.assertEqual(UpgradeOperation.objects.count(), 2)
        device_uo1 = UpgradeOperation.objects.get(device=device1)

        with self.subTest('Test filtering using status'):
            url = reverse('upgrader:api_deviceupgradeoperation_list', args=[device1.pk])
            with self.assertNumQueries(6):
                r = self.client.get(url, {'status': 'in-progress'})
            self.assertEqual(r.status_code, 200)
            serializer_list = self._serialize_device_upgrade_operation(device_uo1)
            self.assertEqual(r.data['results'], [serializer_list])
            with self.assertNumQueries(5):
                r = self.client.get(url, {'status': 'failed'})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.data['results'], [])

    def test_device_uo_list_multitenancy(self):
        d1, d2, device_uo1, device_uo2 = self._create_device_uo_multi_env()

        with self.subTest('Test device upgrade operation detail org manager'):
            self._login('org1_manager', 'tester')
            url = reverse('upgrader:api_deviceupgradeoperation_list', args=[d1.pk])
            with self.assertNumQueries(6):
                r = self.client.get(url)
            self.assertEqual(r.status_code, 200)
            serializer_list = self._serialize_device_upgrade_operation(device_uo1)
            self.assertEqual(r.data['results'], [serializer_list])
            url = reverse('upgrader:api_deviceupgradeoperation_list', args=[d2.pk])
            with self.assertNumQueries(5):
                r = self.client.get(url)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.data['results'], [])

        with self.subTest('Test device upgrade operation org member (403 forbidden)'):
            self._login('org1_member', 'tester')
            url = reverse('upgrader:api_deviceupgradeoperation_list', args=[d1.pk])
            err = 'User is not a manager of the organization'
            with self.assertNumQueries(2):
                r = self.client.get(url)
            self.assertEqual(r.status_code, 403)
            self.assertIn(err, r.json()['detail'])
            url = reverse('upgrader:api_deviceupgradeoperation_list', args=[d2.pk])
            with self.assertNumQueries(2):
                r = self.client.get(url)
            self.assertEqual(r.status_code, 403)
            self.assertIn(err, r.json()['detail'])

        with self.subTest('Test device upgrade operation org admin'):
            self._login('org_admin', 'tester')
            url = reverse('upgrader:api_deviceupgradeoperation_list', args=[d1.pk])
            with self.assertNumQueries(4):
                r = self.client.get(url)
            self.assertEqual(r.status_code, 200)
            serializer_list = self._serialize_device_upgrade_operation(device_uo1)
            self.assertEqual(r.data['results'], [serializer_list])
            url = reverse('upgrader:api_deviceupgradeoperation_list', args=[d2.pk])
            with self.assertNumQueries(4):
                r = self.client.get(url)
            self.assertEqual(r.status_code, 200)
            serializer_list = self._serialize_device_upgrade_operation(device_uo2)
            self.assertEqual(r.data['results'], [serializer_list])


class TestUpgradeOperationViews(TestAPIUpgraderMixin, TestCase):
    def _serialize_upgrade_operation(self, uo, many=False):
        if many:
            serializer = UpgradeOperationSerializer(uo, many=many)
            return serializer.data
        serializer = UpgradeOperationSerializer()
        return dict(serializer.to_representation(uo))

    def _create_upgrade_operation_multi_env(self):
        org1 = self._get_org()
        org2 = self._create_org(name='New org', slug='new-org')
        cat2 = self._create_category(name='New category2', organization=org2)
        build1 = self._get_build()
        build2 = self._create_build(version='0.2', category=cat2)
        image1 = self._create_firmware_image(build=build1)
        image2 = self._create_firmware_image(build=build2)
        d1 = self._create_device(
            name='device1',
            organization=org1,
            mac_address='00:22:bb:33:cc:44',
            model=image1.boards[0],
        )
        d2 = self._create_device(
            name='device2',
            organization=org2,
            mac_address='00:11:bb:22:cc:33',
            model=image2.boards[0],
        )
        ssh_credentials1 = self._get_credentials(organization=org1)
        ssh_credentials2 = self._get_credentials(organization=org2)
        self._create_config(device=d1)
        self._create_config(device=d2)
        self._create_device_connection(device=d1, credentials=ssh_credentials1)
        self._create_device_connection(device=d2, credentials=ssh_credentials2)
        self._create_device_firmware(
            device=d1, image=image1, upgrade=True, device_connection=False
        )
        self._create_device_firmware(
            device=d2, image=image2, upgrade=True, device_connection=False
        )
        self.assertEqual(UpgradeOperation.objects.count(), 2)
        uo1 = UpgradeOperation.objects.get(device=d1)
        uo2 = UpgradeOperation.objects.get(device=d2)
        self._create_operator(
            organizations=[org1],
            username='org1_manager',
            email='orgmanager@test.com',
        )
        self._create_operator(username='org1_member', email='orgmember@test.com')
        self._create_operator(
            username='org_admin', email='org_admin@test.com', is_superuser=True
        )
        return d1, d2, image1, image2, uo1, uo2

    def _assert_uo_list_django_filters(self, query_num, uo, filter_params={}):
        url = reverse('upgrader:api_upgradeoperation_list')
        with self.assertNumQueries(query_num):
            r = self.client.get(url, filter_params)
            self.assertEqual(r.status_code, 200)
            serializer_list = self._serialize_upgrade_operation(uo)
            self.assertEqual(r.data['results'], [serializer_list])

    def test_uo_list_unauthorized(self):
        self._create_device_firmware(upgrade=True)
        client = Client()
        org2 = self._create_org(name='org2', slug='org2')
        OrganizationUser.objects.create(user=self.operator, organization=org2)
        url = reverse('upgrader:api_upgradeoperation_list')
        with self.subTest(url=url):
            with self.assertNumQueries(0):
                r = client.get(url)
            self.assertEqual(r.status_code, 401)

    def test_uo_detail_unauthorized(self):
        device_fw = self._create_device_firmware(upgrade=True)
        client = Client()
        org2 = self._create_org(name='org2', slug='org2')
        OrganizationUser.objects.create(user=self.operator, organization=org2)
        url = reverse(
            'upgrader:api_upgradeoperation_detail', args=[device_fw.device.pk]
        )
        with self.subTest(url=url):
            with self.assertNumQueries(0):
                r = client.get(url)
            self.assertEqual(r.status_code, 401)

    def test_uo_detail_404(self):
        device_pk = uuid.uuid4()
        url = reverse('upgrader:api_upgradeoperation_detail', args=[device_pk])
        with self.assertNumQueries(4):
            r = self.client.get(url)
        self.assertEqual(r.status_code, 404)

    def test_uo_list_get(self):
        self._create_upgrade_env(upgrade_operation=True)
        self.assertEqual(UpgradeOperation.objects.count(), 2)
        uo_qs = UpgradeOperation.objects.order_by('-created')

        with self.subTest('Test when upgrade operations exist'):
            url = reverse('upgrader:api_upgradeoperation_list')
            with self.assertNumQueries(5):
                r = self.client.get(url)
            self.assertEqual(r.status_code, 200)
            serializer_list = self._serialize_upgrade_operation(uo_qs, many=True)
            self.assertEqual(r.data['results'], serializer_list)

        with self.subTest('Test when upgrade operations does not exist'):
            UpgradeOperation.objects.all().delete()
            url = reverse('upgrader:api_upgradeoperation_list')
            with self.assertNumQueries(4):
                r = self.client.get(url)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.data['results'], [])

    def test_uo_detail_get(self):
        self._create_upgrade_env(upgrade_operation=True)
        self.assertEqual(UpgradeOperation.objects.count(), 2)
        uo1 = UpgradeOperation.objects.first()

        with self.subTest('Test when upgrade operations exist'):
            url = reverse('upgrader:api_upgradeoperation_detail', args=[uo1.pk])
            with self.assertNumQueries(5):
                r = self.client.get(url)
            self.assertEqual(r.status_code, 200)
            serializer_list = self._serialize_upgrade_operation(uo1)
            self.assertEqual(r.data, serializer_list)

    def test_uo_list_django_filters(self):
        d1, d2, image1, image2, uo1, uo2 = self._create_upgrade_operation_multi_env()
        self.assertEqual(UpgradeOperation.objects.count(), 2)
        self._login('org_admin', 'tester')

        with self.subTest('Test filtering using organization id'):
            self._assert_uo_list_django_filters(
                4, uo1, {'device__organization': d1.organization_id}
            )
            self._assert_uo_list_django_filters(
                4, uo2, {'device__organization': d2.organization_id}
            )

        with self.subTest('Test filtering using organization slug'):
            self._assert_uo_list_django_filters(
                3, uo1, {'device__organization__slug': d1.organization.slug}
            )
            self._assert_uo_list_django_filters(
                3, uo2, {'device__organization__slug': d2.organization.slug}
            )

        with self.subTest('Test filtering using device id'):
            self._assert_uo_list_django_filters(3, uo1, {'device': d1.pk})
            self._assert_uo_list_django_filters(3, uo2, {'device': d2.pk})

        with self.subTest('Test filtering using image id'):
            self._assert_uo_list_django_filters(3, uo1, {'image': image1.pk})
            self._assert_uo_list_django_filters(3, uo2, {'image': image2.pk})

        with self.subTest('Test filtering using status'):
            uo2.status = 'failed'
            uo2.full_clean()
            uo2.save()
            self._assert_uo_list_django_filters(3, uo1, {'status': 'in-progress'})
            self._assert_uo_list_django_filters(3, uo2, {'status': 'failed'})

    def test_uo_list_detail_multitenancy(self):
        _, _, _, _, uo1, uo2 = self._create_upgrade_operation_multi_env()

        with self.subTest('Test upgrade operation list org manager'):
            self._login('org1_manager', 'tester')
            url = reverse('upgrader:api_upgradeoperation_list')
            with self.assertNumQueries(5):
                r = self.client.get(url)
            self.assertEqual(r.status_code, 200)
            serializer_list = self._serialize_upgrade_operation(uo1)
            self.assertEqual(r.data['results'], [serializer_list])

        with self.subTest('Test upgrade operation detail org manager'):
            self._login('org1_manager', 'tester')
            url = reverse('upgrader:api_upgradeoperation_detail', args=[uo1.pk])
            with self.assertNumQueries(5):
                r = self.client.get(url)
            self.assertEqual(r.status_code, 200)
            serializer_detail = self._serialize_upgrade_operation(uo1)
            self.assertEqual(r.data, serializer_detail)
            url = reverse('upgrader:api_upgradeoperation_detail', args=[uo2.pk])
            with self.assertNumQueries(4):
                r = self.client.get(url)
            self.assertEqual(r.status_code, 404)

        with self.subTest('Test upgrade operation list org member (403 forbidden)'):
            self._login('org1_member', 'tester')
            url = reverse('upgrader:api_upgradeoperation_list')
            err = 'User is not a manager of the organization'
            with self.assertNumQueries(1):
                r = self.client.get(url)
            self.assertEqual(r.status_code, 403)
            self.assertIn(err, r.json()['detail'])

        with self.subTest('Test upgrade operation detail org member (403 forbidden)'):
            self._login('org1_member', 'tester')
            url = reverse('upgrader:api_upgradeoperation_detail', args=[uo1.pk])
            err = 'User is not a manager of the organization'
            with self.assertNumQueries(1):
                r = self.client.get(url)
            self.assertEqual(r.status_code, 403)
            self.assertIn(err, r.json()['detail'])
            url = reverse('upgrader:api_upgradeoperation_detail', args=[uo2.pk])
            with self.assertNumQueries(1):
                r = self.client.get(url)
            self.assertEqual(r.status_code, 403)
            self.assertIn(err, r.json()['detail'])

        with self.subTest('Test upgrade operation list org admin'):
            # The org admin can view upgrade
            # operations for both organizations.
            uo_qs = UpgradeOperation.objects.order_by('-created')
            self._login('org_admin', 'tester')
            url = reverse('upgrader:api_upgradeoperation_list')
            with self.assertNumQueries(3):
                r = self.client.get(url)
            self.assertEqual(r.status_code, 200)
            serializer_list = self._serialize_upgrade_operation(uo_qs, many=True)
            self.assertEqual(r.data['results'], serializer_list)
            url = reverse('upgrader:api_upgradeoperation_list')
            with self.assertNumQueries(3):
                r = self.client.get(url)
            self.assertEqual(r.status_code, 200)
            serializer_list = self._serialize_upgrade_operation(uo_qs, many=True)
            self.assertEqual(r.data['results'], serializer_list)


class TestOrgAPIMixin(TestAPIUpgraderMixin, TestCase):
    def _serialize_build(self, build):
        serializer = BuildSerializer()
        return dict(serializer.to_representation(build))

    def test_user_multiple_organizations(self):
        org2 = self._create_org(name='New org', slug='new-org')
        self._create_operator(
            organizations=[self.org, org2],
            username='operator2',
            email='operator2@test.com',
        )

        self._create_build(version='1.0', organization=self.org)
        self._create_build(version='2.0', organization=org2)

        url = reverse('upgrader:api_build_list')

        self._login('operator2', 'tester')
        serialized_list = [
            self._serialize_build(build)
            for build in Build.objects.all().order_by('-created')
        ]
        with self.assertNumQueries(5):
            r = self.client.get(url)
        self.assertEqual(r.data['results'], serialized_list)
        self.assertEqual(r.status_code, 200)


class TestApiMisc(TestAPIUpgraderMixin, TestCase):
    def test_api_docs(self):
        url = reverse('schema-swagger-ui')

        with self.subTest('not authenticated'):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 403)

        with self.subTest('authenticated'):
            self._create_operator(
                username='admin', email='admin@test.com', is_superuser=True
            )
            self._login('admin', 'tester')
            response = self.client.get(url)
            self.assertEqual(response.status_code, 403)
