import os
from unittest import skipIf

from django.test import TestCase
from django.urls import reverse

from ..models import Build, Category, DeviceFirmware, FirmwareImage, UpgradeOperation
from .base import TestUpgraderMixin
from .base.test_admin import BaseTestAdmin


@skipIf(os.environ.get('SAMPLE_APP', False), 'Running tests on SAMPLE_APP')
class TestAdmin(BaseTestAdmin, TestUpgraderMixin, TestCase):
    BUILD_LIST_URL = reverse('admin:firmware_upgrader_build_changelist')
    device_firmware_model = DeviceFirmware
    upgrade_operation_model = UpgradeOperation
    firmware_image_model = FirmwareImage
    build_model = Build
    category_model = Category
