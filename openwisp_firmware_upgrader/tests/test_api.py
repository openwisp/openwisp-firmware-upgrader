import os
from unittest import skipIf

from django.test import TestCase

from ..models import (
    BatchUpgradeOperation,
    Build,
    Category,
    DeviceFirmware,
    FirmwareImage,
)
from .base.test_api import (
    BaseTestBatchUpgradeOperationViews,
    BaseTestBuildViews,
    BaseTestCategoryViews,
    BaseTestFirmwareImageViews,
)


@skipIf(os.environ.get('SAMPLE_APP', False), 'Running tests on SAMPLE_APP')
class TestBuildViews(BaseTestBuildViews, TestCase):
    build_model = Build
    batch_upgrade_operation_model = BatchUpgradeOperation
    category_model = Category
    device_firmware_model = DeviceFirmware
    firmware_image_model = FirmwareImage


@skipIf(os.environ.get('SAMPLE_APP', False), 'Running tests on SAMPLE_APP')
class TestCategoryViews(BaseTestCategoryViews, TestCase):
    build_model = Build
    batch_upgrade_operation_model = BatchUpgradeOperation
    category_model = Category
    device_firmware_model = DeviceFirmware
    firmware_image_model = FirmwareImage


@skipIf(os.environ.get('SAMPLE_APP', False), 'Running tests on SAMPLE_APP')
class TestBatchUpgradeOperationViews(BaseTestBatchUpgradeOperationViews, TestCase):
    build_model = Build
    batch_upgrade_operation_model = BatchUpgradeOperation
    category_model = Category
    device_firmware_model = DeviceFirmware
    firmware_image_model = FirmwareImage


@skipIf(os.environ.get('SAMPLE_APP', False), 'Running tests on SAMPLE_APP')
class TestFirmwareImageViews(BaseTestFirmwareImageViews, TestCase):
    build_model = Build
    batch_upgrade_operation_model = BatchUpgradeOperation
    category_model = Category
    device_firmware_model = DeviceFirmware
    firmware_image_model = FirmwareImage
