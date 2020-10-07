import uuid

import swapper
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from openwisp_firmware_upgrader.api.serializers import (
    BatchUpgradeOperationListSerializer,
    BatchUpgradeOperationSerializer,
    BuildSerializer,
    CategorySerializer,
    FirmwareImageSerializer,
)
from openwisp_firmware_upgrader.tests.base import TestUpgraderMixin
from openwisp_users.tests.utils import TestMultitenantAdminMixin

from ..swapper import load_model

BatchUpgradeOperation = load_model('BatchUpgradeOperation')
Build = load_model('Build')
Category = load_model('Category')
DeviceFirmware = load_model('DeviceFirmware')
FirmwareImage = load_model('FirmwareImage')
UpgradeOperation = load_model('UpgradeOperation')
OrganizationUser = swapper.load_model('openwisp_users', 'OrganizationUser')

user_model = get_user_model()


class TestAPIUpgraderMixin(TestMultitenantAdminMixin, TestUpgraderMixin):
    def setUp(self):
        self.org = self._get_org()
        self.operator = self._create_operator(organizations=[self.org])
        self._login()

    def _make_operator_org_manager(self):
        orgrelation = OrganizationUser.objects.get(user=self.operator)
        orgrelation.is_admin = True
        orgrelation.save()

    def _obtain_auth_token(self, username='operator', password='tester'):
        params = {'username': username, 'password': password}
        url = reverse('users:user_auth_token')
        r = self.client.post(url, params)
        self.assertEqual(r.status_code, 200)
        return r.data['token']

    def _login(self, username='operator', password='tester'):
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
        with self.assertNumQueries(3):
            r = self.client.get(url)
        self.assertEqual(r.data['results'], serialized_list)

    def test_build_list_django_filters(self):
        category1 = self._create_category()
        category2 = self._create_category(name='New category')

        build1 = self._create_build(category=category1)
        build2 = self._create_build(version='0.2', category=category2)
        url = reverse('upgrader:api_build_list')

        filter_params = dict(category=category1.pk)
        with self.assertNumQueries(4):
            r = self.client.get(url, filter_params)
        self.assertEqual(r.data['results'], [self._serialize_build(build1)])

        filter_params = dict(category=category2.pk)
        with self.assertNumQueries(4):
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
        with self.assertNumQueries(3):
            r = self.client.get(url)
        self.assertEqual(r.data['results'], serialized_list)

        self._login('operator2', 'tester')
        serialized_list = [
            self._serialize_build(build2),
        ]
        with self.assertNumQueries(3):
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
        with self.assertNumQueries(2):
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
        with self.assertNumQueries(9):
            r = self.client.put(url, data, content_type='application/json')
        self.assertEqual(r.data['id'], str(build.pk))
        self.assertEqual(r.data['category'], build.category.pk)
        self.assertEqual(r.data['version'], '20.04')
        self.assertEqual(r.data['changelog'], 'PUT update')

    def test_build_update_partial(self):
        build = self._create_build()
        url = reverse('upgrader:api_build_detail', args=[build.pk])
        data = dict(changelog='PATCH update')
        with self.assertNumQueries(8):
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
            with self.assertNumQueries(7):
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
            self.assertEqual(r.json(), {'detail': 'Not found.'})

    def test_build_upgradeable(self):
        env = self._create_upgrade_env()
        self.assertEqual(BatchUpgradeOperation.objects.count(), 0)

        url = reverse('upgrader:api_build_batch_upgrade', args=[env['build2'].pk])
        with self.assertNumQueries(7):
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
        with self.assertNumQueries(2):
            r = self.client.get(url)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json(), {'detail': 'Not found.'})
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
        OrganizationUser.objects.create(user=self.operator, organization=org2)

        url = reverse('upgrader:api_category_detail', args=[category.pk])
        with self.assertNumQueries(2):
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
        with self.assertNumQueries(3):
            r = self.client.get(url)
        self.assertEqual(r.data['results'], serialized_list)

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
        with self.assertNumQueries(3):
            r = self.client.get(url)
        self.assertEqual(r.data['results'], serialized_list)

        self._login('operator2', 'tester')
        serialized_list = [
            self._serialize_category(category2),
        ]
        with self.assertNumQueries(3):
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
        with self.assertNumQueries(2):
            r = self.client.get(url)
        self.assertEqual(r.data, serialized)

    def test_category_update(self):
        category = self._get_category()
        url = reverse('upgrader:api_category_detail', args=[category.pk])
        data = {
            'name': 'New name',
            'organization': category.organization.pk,
        }
        with self.assertNumQueries(9):
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
        self.operator.openwisp_users_organization.all().delete()
        OrganizationUser.objects.create(user=self.operator, organization=org2)

        url = reverse(
            'upgrader:api_batchupgradeoperation_detail', args=[env['build2'].pk]
        )
        with self.assertNumQueries(2):
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
        with self.assertNumQueries(3):
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
        with self.assertNumQueries(3):
            r = self.client.get(url)
        self.assertEqual(r.data['results'], serialized_list)

        operation = BatchUpgradeOperation.objects.get(build=env['build1'])
        serialized_list = [self._serialize_upgrade_env(operation)]
        filter_params = dict(build=env['build1'].pk)
        with self.assertNumQueries(4):
            r = self.client.get(url, filter_params)
        self.assertEqual(r.data['results'], serialized_list)

        operation = BatchUpgradeOperation.objects.get(build=env['build2'])
        serialized_list = [self._serialize_upgrade_env(operation)]
        filter_params = dict(build=env['build2'].pk)
        with self.assertNumQueries(4):
            r = self.client.get(url, filter_params)
        self.assertEqual(r.data['results'], serialized_list)

        serialized_list = [
            self._serialize_upgrade_env(operation)
            for operation in BatchUpgradeOperation.objects.filter(
                status='in-progress'
            ).order_by('-created')
        ]
        filter_params = dict(status='in-progress')
        with self.assertNumQueries(2):
            r = self.client.get(url, filter_params)
        self.assertEqual(r.data['results'], serialized_list)

        serialized_list = [
            self._serialize_upgrade_env(operation)
            for operation in BatchUpgradeOperation.objects.filter(
                status='success'
            ).order_by('-created')
        ]
        filter_params = dict(status='success')
        with self.assertNumQueries(2):
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
        with self.assertNumQueries(3):
            r = self.client.get(url)
        self.assertEqual(r.data['results'], serialized_list)

        self._login('operator2', 'tester')
        operation2 = BatchUpgradeOperation.objects.get(build=env2['build2'])
        serialized_list = [self._serialize_upgrade_env(operation2)]
        with self.assertNumQueries(3):
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
        with self.assertNumQueries(4):
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
        with self.assertNumQueries(4):
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
        with self.assertNumQueries(4):
            r = self.client.get(url, filter_params)
        self.assertEqual(r.data['results'], [self._serialize_image(image)])

        url = reverse('upgrader:api_firmware_list', args=[image.build.pk])

        filter_params = dict(type=self.TPLINK_4300_IL_IMAGE)
        with self.assertNumQueries(4):
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
        with self.assertNumQueries(4):
            r = self.client.get(url)
        self.assertEqual(r.data['results'], serialized_list)

        url = reverse('upgrader:api_firmware_list', args=[image2.build.pk])
        self._login('operator2', 'tester')
        serialized_list = [self._serialize_image(image2)]
        with self.assertNumQueries(4):
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
        with self.assertNumQueries(3):
            r = self.client.get(url)
        self.assertEqual(r.data, serialized)

    def test_firmware_delete(self):
        image = self._create_firmware_image()
        self.assertEqual(FirmwareImage.objects.count(), 1)
        url = reverse('upgrader:api_firmware_detail', args=[image.build.pk, image.pk])
        with self.assertNumQueries(10):
            r = self.client.delete(url)
        self.assertEqual(r.status_code, 204)
        self.assertEqual(FirmwareImage.objects.count(), 0)

    def test_firmware_download(self):
        image = self._create_firmware_image()
        with open(self.FAKE_IMAGE_PATH, 'rb') as f:
            content = f.read()
        url = reverse('upgrader:api_firmware_download', args=[image.build.pk, image.pk])
        with self.subTest("Test as operator"):
            self._make_operator_org_manager()
            with self.assertNumQueries(6):
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
        with self.assertNumQueries(3):
            r = self.client.get(url)
        self.assertEqual(r.data['results'], serialized_list)
        self.assertEqual(r.status_code, 200)
