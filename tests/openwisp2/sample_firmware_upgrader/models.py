from django.db import models
from openwisp_firmware_upgrader.base.models import (AbstractBatchUpgradeOperation, AbstractBuild,
                                                    AbstractCategory, AbstractDeviceFirmware,
                                                    AbstractFirmwareImage, AbstractUpgradeOperation)


class DetailsModel(models.Model):
    details = models.CharField(max_length=64, blank=True, null=True)

    class Meta:
        abstract = True


class Category(DetailsModel, AbstractCategory):
    pass


class Build(DetailsModel, AbstractBuild):
    pass


class FirmwareImage(DetailsModel, AbstractFirmwareImage):
    pass


class DeviceFirmware(DetailsModel, AbstractDeviceFirmware):
    pass


class BatchUpgradeOperation(DetailsModel, AbstractBatchUpgradeOperation):
    pass


class UpgradeOperation(DetailsModel, AbstractUpgradeOperation):
    pass
