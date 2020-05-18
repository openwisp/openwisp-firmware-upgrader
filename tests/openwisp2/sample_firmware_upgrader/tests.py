from django.urls import reverse
from openwisp_firmware_upgrader.swapper import load_model
from openwisp_firmware_upgrader.tests.test_admin import TestAdmin as BaseTestAdmin
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


# this is necessary to avoid excuting the base test suites
del BaseTestModels
del BaseTestAdmin
del BaseTestModelsTransaction
del BaseTestOpenwrtUpgrader
del BaseTestPrivateStorage
del BaseTestTasks
