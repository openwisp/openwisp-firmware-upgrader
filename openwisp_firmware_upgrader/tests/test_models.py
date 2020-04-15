import os
from unittest import skipIf

from django.test import TestCase, TransactionTestCase

from ..models import (
    BatchUpgradeOperation,
    Build,
    Category,
    DeviceFirmware,
    FirmwareImage,
    UpgradeOperation,
)
from .base import TestUpgraderMixin
from .base.test_models import BaseTestModels, BaseTestModelsTransaction


@skipIf(os.environ.get('SAMPLE_APP', False), 'Running tests on SAMPLE_APP')
class TestModels(BaseTestModels, TestUpgraderMixin, TestCase):
    app_name = 'openwisp_firmware_upgrader'
    device_firmware_model = DeviceFirmware
    upgrade_operation_model = UpgradeOperation
    batch_upgrade_operation_model = BatchUpgradeOperation
    firmware_image_model = FirmwareImage
    build_model = Build
    category_model = Category


@skipIf(os.environ.get('SAMPLE_APP', False), 'Running tests on SAMPLE_APP')
class TestModelsTransaction(
    BaseTestModelsTransaction, TestUpgraderMixin, TransactionTestCase
):
    device_firmware_model = DeviceFirmware
    upgrade_operation_model = UpgradeOperation
    batch_upgrade_operation_model = BatchUpgradeOperation
    firmware_image_model = FirmwareImage
    build_model = Build
    category_model = Category
