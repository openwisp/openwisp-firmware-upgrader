from django.db import models

from openwisp_firmware_upgrader.base.models import (
    AbstractBatchUpgradeOperation,
    AbstractBuild,
    AbstractCategory,
    AbstractDeviceFirmware,
    AbstractFirmwareImage,
    AbstractUpgradeOperation,
)


class DetailsModel(models.Model):
    details = models.CharField(max_length=64, blank=True, null=True)

    class Meta:
        abstract = True


class Category(DetailsModel, AbstractCategory):
    class Meta(AbstractCategory.Meta):
        abstract = False


class Build(DetailsModel, AbstractBuild):
    class Meta(AbstractBuild.Meta):
        abstract = False


class FirmwareImage(DetailsModel, AbstractFirmwareImage):
    class Meta(AbstractFirmwareImage.Meta):
        abstract = False


class DeviceFirmware(DetailsModel, AbstractDeviceFirmware):
    class Meta(AbstractDeviceFirmware.Meta):
        abstract = False


class BatchUpgradeOperation(DetailsModel, AbstractBatchUpgradeOperation):
    class Meta(AbstractBatchUpgradeOperation.Meta):
        abstract = False


class UpgradeOperation(DetailsModel, AbstractUpgradeOperation):
    class Meta(AbstractUpgradeOperation.Meta):
        abstract = False
