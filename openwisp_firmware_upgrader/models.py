from swapper import swappable_setting

from .base.models import (
    AbstractBatchUpgradeOperation,
    AbstractBuild,
    AbstractCategory,
    AbstractDeviceFirmware,
    AbstractFirmwareImage,
    AbstractUpgradeOperation,
)


class Category(AbstractCategory):
    class Meta(AbstractCategory.Meta):
        abstract = False
        swappable = swappable_setting('firmware_upgrader', 'Category')


class Build(AbstractBuild):
    class Meta(AbstractBuild.Meta):
        abstract = False
        swappable = swappable_setting('firmware_upgrader', 'Build')


class FirmwareImage(AbstractFirmwareImage):
    class Meta(AbstractFirmwareImage.Meta):
        abstract = False
        swappable = swappable_setting('firmware_upgrader', 'FirmwareImage')


class DeviceFirmware(AbstractDeviceFirmware):
    class Meta(AbstractDeviceFirmware.Meta):
        abstract = False
        swappable = swappable_setting('firmware_upgrader', 'DeviceFirmware')


class BatchUpgradeOperation(AbstractBatchUpgradeOperation):
    class Meta(AbstractBatchUpgradeOperation.Meta):
        abstract = False
        swappable = swappable_setting('firmware_upgrader', 'BatchUpgradeOperation')


class UpgradeOperation(AbstractUpgradeOperation):
    class Meta(AbstractUpgradeOperation.Meta):
        abstract = False
        swappable = swappable_setting('firmware_upgrader', 'UpgradeOperation')
