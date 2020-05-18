import os
from unittest import skipUnless

from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from openwisp_firmware_upgrader.swapper import load_model
from openwisp_firmware_upgrader.tests.base import TestUpgraderMixin
from openwisp_firmware_upgrader.tests.base.test_admin import BaseTestAdmin
from openwisp_firmware_upgrader.tests.base.test_models import (
    BaseTestModels,
    BaseTestModelsTransaction,
)
from openwisp_firmware_upgrader.tests.base.test_openwrt_upgrader import (
    BaseTestOpenwrtUpgrader,
)
from openwisp_firmware_upgrader.tests.base.test_private_storage import (
    BaseTestPrivateStorage,
)
from openwisp_firmware_upgrader.tests.base.test_tasks import BaseTestTasks

BatchUpgradeOperation = load_model('BatchUpgradeOperation')
Build = load_model('Build')
Category = load_model('Category')
DeviceFirmware = load_model('DeviceFirmware')
FirmwareImage = load_model('FirmwareImage')
UpgradeOperation = load_model('UpgradeOperation')


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
class TestOpenwrtUpgrader(BaseTestOpenwrtUpgrader, TransactionTestCase):
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
