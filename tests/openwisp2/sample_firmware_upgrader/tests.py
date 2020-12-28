from django.urls import reverse

from openwisp_firmware_upgrader.swapper import load_model
from openwisp_firmware_upgrader.tests.test_admin import TestAdmin as BaseTestAdmin
from openwisp_firmware_upgrader.tests.test_admin import (
    TestAdminTransaction as BaseTestAdminTransaction,
)
from openwisp_firmware_upgrader.tests.test_api import (
    TestBatchUpgradeOperationViews as BaseTestBatchUpgradeOperationViews,
)
from openwisp_firmware_upgrader.tests.test_api import (
    TestBuildViews as BaseTestBuildViews,
)
from openwisp_firmware_upgrader.tests.test_api import (
    TestCategoryViews as BaseTestCategoryViews,
)
from openwisp_firmware_upgrader.tests.test_api import (
    TestFirmwareImageViews as BaseTestFirmwareImageViews,
)
from openwisp_firmware_upgrader.tests.test_api import (
    TestOrgAPIMixin as BaseTestOrgAPIMixin,
)
from openwisp_firmware_upgrader.tests.test_models import TestModels as BaseTestModels
from openwisp_firmware_upgrader.tests.test_models import (
    TestModelsTransaction as BaseTestModelsTransaction,
)
from openwisp_firmware_upgrader.tests.test_openwrt_upgrader import (
    TestOpenwrtUpgrader as BaseTestOpenwrtUpgrader,
)
from openwisp_firmware_upgrader.tests.test_private_storage import (
    TestPrivateStorage as BaseTestPrivateStorage,
)
from openwisp_firmware_upgrader.tests.test_tasks import TestTasks as BaseTestTasks

BatchUpgradeOperation = load_model('BatchUpgradeOperation')
Build = load_model('Build')
Category = load_model('Category')
DeviceFirmware = load_model('DeviceFirmware')
FirmwareImage = load_model('FirmwareImage')
UpgradeOperation = load_model('UpgradeOperation')


class TestAdmin(BaseTestAdmin):
    app_label = 'sample_firmware_upgrader'
    build_list_url = reverse(f'admin:{app_label}_build_changelist')

    def test_category_details(self):
        self._login()
        category = self._create_category(details='sample category details')
        path = reverse(f'admin:{self.app_label}_category_change', args=[category.pk])
        r = self.client.get(path)
        self.assertContains(
            r, '<input type="text" name="details" value="sample category details"'
        )

    def test_build_details(self):
        self._login()
        build = self._create_build(details='sample build details')
        path = reverse(f'admin:{self.app_label}_build_change', args=[build.pk])
        r = self.client.get(path)
        self.assertContains(
            r, '<input type="text" name="details" value="sample build details"'
        )

    def test_firmware_image_details(self):
        self._login()
        build = self._create_build()
        self._create_firmware_image(details='sample fw_image details', build=build)
        path = reverse(f'admin:{self.app_label}_build_change', args=[build.pk])
        r = self.client.get(path)
        self.assertContains(r, '<div class="readonly">sample fw_image details')

    def test_device_firmware_details(self):
        self._login()
        device_fw = self._create_device_firmware(details='sample device_fw details')
        path = reverse('admin:config_device_change', args=[device_fw.device_id])
        r = self.client.get(path)
        self.assertContains(
            r,
            '<input type="text" name="devicefirmware-0-details" '
            'value="sample device_fw details" class="vTextField"',
        )

    def test_batch_upgrade_operation_details(self):
        self._login()
        env = self._create_upgrade_env()
        env['build1'].batch_upgrade(firmwareless=True)
        buo = BatchUpgradeOperation.objects.first()
        buo.details = 'Test BatchUpgrade details'
        buo.save()
        url = reverse(
            f'admin:{self.app_label}_batchupgradeoperation_change', args=[buo.pk]
        )
        r = self.client.get(url)
        self.assertContains(r, '<div class="readonly">Test BatchUpgrade details')

    def test_upgrede_operation_details(self):
        self._login()
        device_fw = self._create_device_firmware()
        device_fw.save(upgrade=True)
        uo = UpgradeOperation.objects.first()
        uo.details = 'Test Upgrade device details'
        uo.save()
        url = reverse('admin:config_device_change', args=[device_fw.device.pk])
        r = self.client.get(url)
        self.assertContains(r, '<div class="readonly">Test Upgrade device details')


class TestAdminTransaction(BaseTestAdminTransaction):
    app_label = 'sample_firmware_upgrader'
    build_list_url = reverse(f'admin:{app_label}_build_changelist')


class TestModels(BaseTestModels):
    app_label = 'openwisp2.sample_firmware_upgrader'


class TestModelsTransaction(BaseTestModelsTransaction):
    pass


class TestOpenwrtUpgrader(BaseTestOpenwrtUpgrader):
    pass


class TestPrivateStorage(BaseTestPrivateStorage):
    pass


class TestTasks(BaseTestTasks):
    pass


class TestBuildViews(BaseTestBuildViews):
    pass


class TestCategoryViews(BaseTestCategoryViews):
    pass


class TestBatchUpgradeOperationViews(BaseTestBatchUpgradeOperationViews):
    pass


class TestFirmwareImageViews(BaseTestFirmwareImageViews):
    pass


class TestOrgAPIMixin(BaseTestOrgAPIMixin):
    pass


# this is necessary to avoid excuting the base test suites
del BaseTestModels
del BaseTestAdmin
del BaseTestAdminTransaction
del BaseTestModelsTransaction
del BaseTestOpenwrtUpgrader
del BaseTestPrivateStorage
del BaseTestTasks
del BaseTestBuildViews
del BaseTestCategoryViews
del BaseTestBatchUpgradeOperationViews
del BaseTestFirmwareImageViews
del BaseTestOrgAPIMixin
