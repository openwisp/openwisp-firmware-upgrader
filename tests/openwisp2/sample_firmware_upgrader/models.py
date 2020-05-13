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
    class Meta:
        unique_together = ('name', 'organization')


class Build(DetailsModel, AbstractBuild):
    class Meta:
        unique_together = ('category', 'version')


class FirmwareImage(DetailsModel, AbstractFirmwareImage):
    class Meta:
        unique_together = ('build', 'type')


class DeviceFirmware(DetailsModel, AbstractDeviceFirmware):
    pass


class BatchUpgradeOperation(DetailsModel, AbstractBatchUpgradeOperation):
    pass


class UpgradeOperation(DetailsModel, AbstractUpgradeOperation):
    pass
