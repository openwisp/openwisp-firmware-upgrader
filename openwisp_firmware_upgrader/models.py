from swapper import swappable_setting
from django.db import models

from .base.models import (
    AbstractBatchUpgradeOperation,
    AbstractBuild,
    AbstractCategory,
    AbstractDeviceFirmware,
    AbstractFirmwareImage,
    AbstractUpgradeOperation,
)

# Import Location model (for ForeignKey)
import swapper
Location = swapper.load_model("geo", "Location")


class Category(AbstractCategory):
    class Meta(AbstractCategory.Meta):
        abstract = False
        swappable = swappable_setting("firmware_upgrader", "Category")


class Build(AbstractBuild):
    class Meta(AbstractBuild.Meta):
        abstract = False
        swappable = swappable_setting("firmware_upgrader", "Build")


class FirmwareImage(AbstractFirmwareImage):
    class Meta(AbstractFirmwareImage.Meta):
        abstract = False
        swappable = swappable_setting("firmware_upgrader", "FirmwareImage")


class DeviceFirmware(AbstractDeviceFirmware):
    class Meta(AbstractDeviceFirmware.Meta):
        abstract = False
        swappable = swappable_setting("firmware_upgrader", "DeviceFirmware")


class BatchUpgradeOperation(AbstractBatchUpgradeOperation):
    # Explicitly declare the field so Django generates the migration
    location = models.ForeignKey(
        Location,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        help_text="Target only devices at this location",
    )

    class Meta(AbstractBatchUpgradeOperation.Meta):
        abstract = False
        swappable = swappable_setting("firmware_upgrader", "BatchUpgradeOperation")


class UpgradeOperation(AbstractUpgradeOperation):
    class Meta(AbstractUpgradeOperation.Meta):
        abstract = False
        swappable = swappable_setting("firmware_upgrader", "UpgradeOperation")
