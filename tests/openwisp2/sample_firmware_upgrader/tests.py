import os
from unittest import skipUnless

from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from openwisp_firmware_upgrader.tests.base import TestUpgraderMixin
from openwisp_firmware_upgrader.tests.base.test_admin import BaseTestAdmin
from openwisp_firmware_upgrader.tests.base.test_api import (
    BaseTestBatchUpgradeOperationViews,
    BaseTestBuildViews,
    BaseTestCategoryViews,
    BaseTestFirmwareImageViews,
)
from openwisp_firmware_upgrader.tests.base.test_models import (
    BaseTestModels,
    BaseTestModelsTransaction,
)
from openwisp_firmware_upgrader.tests.base.test_private_storage import (
    BaseTestPrivateStorage,
)
from openwisp_firmware_upgrader.tests.base.test_tasks import BaseTestTasks
from swapper import load_model

BatchUpgradeOperation = load_model('firmware_upgrader', 'BatchUpgradeOperation')
Build = load_model('firmware_upgrader', 'Build')
Category = load_model('firmware_upgrader', 'Category')
DeviceFirmware = load_model('firmware_upgrader', 'DeviceFirmware')
FirmwareImage = load_model('firmware_upgrader', 'FirmwareImage')
UpgradeOperation = load_model('firmware_upgrader', 'UpgradeOperation')


@skipUnless(
    os.environ.get('SAMPLE_APP', False),
    'Running tests on standard openwisp_firmware_upgrader models',
)
class TestAdmin(BaseTestAdmin, TestUpgraderMixin, TestCase):
    app_label = 'sample_firmware_upgrader'
    build_list_url = reverse(f'admin:{app_label}_build_changelist')
    device_firmware_model = DeviceFirmware
    upgrade_operation_model = UpgradeOperation
    firmware_image_model = FirmwareImage
    build_model = Build
    category_model = Category


@skipUnless(
    os.environ.get('SAMPLE_APP', False),
    'Running tests on standard openwisp_firmware_upgrader models',
)
class TestModels(BaseTestModels, TestUpgraderMixin, TestCase):
    app_name = 'openwisp2.sample_firmware_upgrader'
    device_firmware_model = DeviceFirmware
    upgrade_operation_model = UpgradeOperation
    batch_upgrade_operation_model = BatchUpgradeOperation
    firmware_image_model = FirmwareImage
    build_model = Build
    category_model = Category


@skipUnless(
    os.environ.get('SAMPLE_APP', False),
    'Running tests on standard openwisp_firmware_upgrader models',
)
class TestModelsTransaction(
    BaseTestModelsTransaction, TestUpgraderMixin, TransactionTestCase
):
    device_firmware_model = DeviceFirmware
    upgrade_operation_model = UpgradeOperation
    batch_upgrade_operation_model = BatchUpgradeOperation
    firmware_image_model = FirmwareImage
    build_model = Build
    category_model = Category


@skipUnless(
    os.environ.get('SAMPLE_APP', False),
    'Running tests on standard openwisp_firmware_upgrader models',
)
class TestPrivateStorage(BaseTestPrivateStorage, TestUpgraderMixin, TestCase):
    device_firmware_model = DeviceFirmware
    upgrade_operation_model = UpgradeOperation
    batch_upgrade_operation_model = BatchUpgradeOperation
    firmware_image_model = FirmwareImage
    build_model = Build
    category_model = Category


@skipUnless(
    os.environ.get('SAMPLE_APP', False),
    'Running tests on standard openwisp_firmware_upgrader models',
)
class TestTasks(BaseTestTasks, TestUpgraderMixin, TransactionTestCase):
    device_firmware_model = DeviceFirmware
    upgrade_operation_model = UpgradeOperation
    batch_upgrade_operation_model = BatchUpgradeOperation
    firmware_image_model = FirmwareImage
    build_model = Build
    category_model = Category


@skipUnless(
    os.environ.get('SAMPLE_APP', False),
    'Running tests on standard openwisp_firmware_upgrader models',
)
class TestBuildViews(BaseTestBuildViews, TestCase):
    device_firmware_model = DeviceFirmware
    upgrade_operation_model = UpgradeOperation
    firmware_image_model = FirmwareImage
    build_model = Build
    category_model = Category


@skipUnless(
    os.environ.get('SAMPLE_APP', False),
    'Running tests on standard openwisp_firmware_upgrader models',
)
class TestCategoryViews(BaseTestCategoryViews, TestCase):
    device_firmware_model = DeviceFirmware
    upgrade_operation_model = UpgradeOperation
    firmware_image_model = FirmwareImage
    build_model = Build
    category_model = Category


@skipUnless(
    os.environ.get('SAMPLE_APP', False),
    'Running tests on standard openwisp_firmware_upgrader models',
)
class TestBatchUpgradeOperationViews(BaseTestBatchUpgradeOperationViews, TestCase):
    device_firmware_model = DeviceFirmware
    upgrade_operation_model = UpgradeOperation
    firmware_image_model = FirmwareImage
    build_model = Build
    category_model = Category


@skipUnless(
    os.environ.get('SAMPLE_APP', False),
    'Running tests on standard openwisp_firmware_upgrader models',
)
class TestFirmwareImageViews(BaseTestFirmwareImageViews, TestCase):
    device_firmware_model = DeviceFirmware
    upgrade_operation_model = UpgradeOperation
    firmware_image_model = FirmwareImage
    build_model = Build
    category_model = Category
