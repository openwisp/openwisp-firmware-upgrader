from __future__ import absolute_import, unicode_literals

import logging
import os
from decimal import Decimal

from celery import shared_task
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import models, transaction
from django.utils.encoding import python_2_unicode_compatible
from django.utils.functional import cached_property
from django.utils.module_loading import import_string
from django.utils.translation import ugettext_lazy as _

from openwisp_controller.config.models import Device
from openwisp_controller.connection.settings import DEFAULT_UPDATE_STRATEGIES
from openwisp_users.mixins import OrgMixin
from openwisp_utils.base import TimeStampedEditableModel

from .hardware import FIRMWARE_IMAGE_MAP, FIRMWARE_IMAGE_TYPE_CHOICES
from .upgraders.openwrt import AbortedUpgrade

logger = logging.getLogger(__name__)


@python_2_unicode_compatible
class Category(OrgMixin, TimeStampedEditableModel):
    name = models.CharField(max_length=64, db_index=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = _('category')
        verbose_name_plural = _('categories')
        unique_together = ('name', 'organization')


@python_2_unicode_compatible
class Build(TimeStampedEditableModel):
    category = models.ForeignKey(Category, on_delete=models.CASCADE,
                                 verbose_name=_('firmware category'),
                                 help_text=_('if you have different firmware types '
                                             'eg: (BGP routers, wifi APs, DSL gateways) '
                                             'create a category for each.'))
    version = models.CharField(max_length=32, db_index=True)
    changelog = models.TextField(_('change log'), blank=True,
                                 help_text=_('descriptive text indicating what '
                                             'has changed since the previous '
                                             'version, if applicable'))

    class Meta:
        unique_together = ('category', 'version')
        ordering = ('-created',)

    def __str__(self):
        try:
            return '{0} v{1}'.format(self.category, self.version)
        except ObjectDoesNotExist:
            return super(Build, self).__str__()

    def batch_upgrade(self, firmwareless):
        batch = BatchUpgradeOperation(build=self)
        batch.full_clean()
        batch.save()
        self.upgrade_related_devices(batch)
        if firmwareless:
            self.upgrade_firmwareless_devices(batch)

    def upgrade_related_devices(self, batch):
        """
        upgrades all devices which have an
        existing related DeviceFirmware
        """
        device_firmwares = self._find_related_device_firmwares()
        for device_fw in device_firmwares:
            image = self.firmwareimage_set.filter(type=device_fw.image.type) \
                                          .first()
            if image:
                device_fw.image = image
                device_fw.full_clean()
                device_fw.save(batch)

    def _find_related_device_firmwares(self, select_devices=False):
        related = ['image']
        if select_devices:
            related.append('device')
        return DeviceFirmware.objects.all() \
                             .select_related(*related) \
                             .filter(image__build__category_id=self.category_id) \
                             .exclude(image__build=self, installed=True)

    def upgrade_firmwareless_devices(self, batch):
        """
        upgrades all devices which do not
        have a related DeviceFirmware yet
        (referred as "firmwareless")
        """
        # for each image, find related "firmwareless"
        # devices and perform upgrade one by one
        for image in self.firmwareimage_set.all():
            devices = self._find_firmwareless_devices(image.boards)
            for device in devices:
                device_fw = DeviceFirmware(device=device,
                                           image=image)
                device_fw.full_clean()
                device_fw.save(batch)

    def _find_firmwareless_devices(self, boards=None):
        """
        returns a queryset used to find "firmwareless" devices
        according to the ``board`` parameter passed;
        if ``board`` is ``None`` all related image boads are searched
        """
        if boards is None:
            boards = []
            for image in self.firmwareimage_set.all():
                boards += image.boards
        return Device.objects.filter(devicefirmware__isnull=True,
                                     organization=self.category.organization,
                                     model__in=boards)


@python_2_unicode_compatible
class FirmwareImage(TimeStampedEditableModel):
    build = models.ForeignKey(Build, on_delete=models.CASCADE)
    file = models.FileField()
    type = models.CharField(blank=True,
                            max_length=128,
                            choices=FIRMWARE_IMAGE_TYPE_CHOICES,
                            help_text=_('firmware image type: model or '
                                        'architecture. Leave blank to attempt '
                                        'determining automatically'))

    class Meta:
        unique_together = ('build', 'type')

    def __str__(self):
        if hasattr(self, 'build') and self.file.name:
            return '{0}: {1}'.format(self.build, self.file.name)
        return super(FirmwareImage, self).__str__()

    @property
    def boards(self):
        return FIRMWARE_IMAGE_MAP[self.type]['boards']

    def clean(self):
        self._clean_type()
        try:
            self.boards
        except KeyError:
            raise ValidationError({
                'type': 'Could not find boards for this type'
            })

    def delete(self, *args, **kwargs):
        super(FirmwareImage, self).delete(*args, **kwargs)
        self._remove_file()

    def _clean_type(self):
        """
        auto determine type if missing
        """
        if self.type:
            return
        filename = self.file.name
        # removes leading prefix
        self.type = '-'.join(filename.split('-')[1:])

    def _remove_file(self):
        path = self.file.path
        if os.path.isfile(path):
            os.remove(path)
        else:
            msg = 'firmware image not found while deleting {0}:\n{1}'
            logger.error(msg.format(self, path))


@python_2_unicode_compatible
class DeviceFirmware(TimeStampedEditableModel):
    device = models.OneToOneField('config.Device', on_delete=models.CASCADE,)
    image = models.ForeignKey(FirmwareImage, on_delete=models.CASCADE)
    installed = models.BooleanField(default=False)
    _old_image = None

    def __init__(self, *args, **kwargs):
        super(DeviceFirmware, self).__init__(*args, **kwargs)
        self._update_old_image()

    def clean(self):
        if self.image.build.category.organization != self.device.organization:
            raise ValidationError({
                'image': _('The organization of the image doesn\'t '
                           'match the organization of the device')
            })
        if self.device.deviceconnection_set.count() < 1:
            raise ValidationError(
                _('This device does not have a related connection object defined '
                  'yet and therefore it would not be possible to upgrade it, '
                  'please add one in the section named "DEVICE CONNECTIONS"')
            )
        if self.device.model not in self.image.boards:
            raise ValidationError(
                _('Device model and image model do not match')
            )

    @property
    def image_has_changed(self):
        return (
            self._state.adding or
            self.image_id != self._old_image.id
        )

    def save(self, batch=None, upgrade=True, *args, **kwargs):
        # if firwmare image has changed launch upgrade
        # upgrade won't be launched the first time
        if upgrade and (self.image_has_changed or not self.installed):
            self.installed = False
            super(DeviceFirmware, self).save(*args, **kwargs)
            self.create_upgrade_operation(batch)
        else:
            super(DeviceFirmware, self).save(*args, **kwargs)
        self._update_old_image()

    def _update_old_image(self):
        if hasattr(self, 'image'):
            self._old_image = self.image

    def create_upgrade_operation(self, batch):
        operation = UpgradeOperation(device=self.device,
                                     image=self.image)
        if batch:
            operation.batch = batch
        operation.full_clean()
        operation.save()
        # launch ``upgrade_firmware`` in the background (celery)
        # once changes are committed to the database
        transaction.on_commit(lambda: upgrade_firmware.delay(operation.pk))
        return operation


UPGRADERS_MAPPING = {
    DEFAULT_UPDATE_STRATEGIES[0][0]: 'openwisp_firmware_upgrader.upgraders.openwrt.OpenWrt'
}


@python_2_unicode_compatible
class BatchUpgradeOperation(TimeStampedEditableModel):
    build = models.ForeignKey(Build, on_delete=models.CASCADE)
    STATUS_CHOICES = (
        ('in-progress', _('in progress')),
        ('success', _('completed successfully')),
        ('failed', _('completed with some failures')),
    )
    status = models.CharField(max_length=12,
                              choices=STATUS_CHOICES,
                              default=STATUS_CHOICES[0][0])

    class Meta:
        verbose_name = _('Mass upgrade operation')
        verbose_name_plural = _('Mass upgrade operations')

    def __str__(self):
        return 'Upgrade of {} on {}'.format(self.build, self.created)

    def update(self):
        operations = self.upgradeoperation_set
        if operations.filter(status='in-progress').exists():
            return
        # if there's any failed operation, mark as failure
        if operations.filter(status='failed').exists():
            self.status = 'failed'
        else:
            self.status = 'success'
        self.save()

    @cached_property
    def upgrade_operations(self):
        return self.upgradeoperation_set.all()

    @cached_property
    def total_operations(self):
        return self.upgrade_operations.count()

    @property
    def progress_report(self):
        completed = self.upgrade_operations.exclude(status='in-progress').count()
        return _('{} out of {}').format(completed, self.total_operations)

    @property
    def success_rate(self):
        if not self.total_operations:
            return 0
        success = self.upgrade_operations.filter(status='success').count()
        return self.__get_rate(success)

    @property
    def failed_rate(self):
        if not self.total_operations:
            return 0
        failed = self.upgrade_operations.filter(status='failed').count()
        return self.__get_rate(failed)

    @property
    def aborted_rate(self):
        if not self.total_operations:
            return 0
        aborted = self.upgrade_operations.filter(status='aborted').count()
        return self.__get_rate(aborted)

    def __get_rate(self, number):
        return Decimal(number) / Decimal(self.total_operations) * 100


@python_2_unicode_compatible
class UpgradeOperation(TimeStampedEditableModel):
    STATUS_CHOICES = (
        ('in-progress', _('in progress')),
        ('success', _('success')),
        ('failed', _('failed')),
        ('aborted', _('aborted')),
    )
    device = models.ForeignKey('config.Device', on_delete=models.CASCADE)
    image = models.ForeignKey(FirmwareImage, on_delete=models.CASCADE)
    status = models.CharField(max_length=12,
                              choices=STATUS_CHOICES,
                              default=STATUS_CHOICES[0][0])
    log = models.TextField(blank=True)
    batch = models.ForeignKey(BatchUpgradeOperation,
                              on_delete=models.CASCADE,
                              blank=True,
                              null=True)

    def upgrade(self):
        conn = self.device.deviceconnection_set.first()
        installed = False
        if not conn:
            self.log = 'No device connection available'
            self.save()
            return
        # prevent multiple upgrade operations for
        # the same device running at the same time
        qs = UpgradeOperation.objects.filter(device=self.device,
                                             status='in-progress') \
                                     .exclude(pk=self.pk)
        if qs.count() > 0:
            message = 'Another upgrade operation is in progress, aborting...'
            logger.warn(message)
            self.status = 'aborted'
            self.log = message
            self.save()
            return
        try:
            upgrader_class = UPGRADERS_MAPPING[conn.update_strategy]
            upgrader_class = import_string(upgrader_class)
        except (AttributeError, ImportError) as e:
            logger.exception(e)
            return
        upgrader = upgrader_class(params=conn.get_params(),
                                  addresses=conn.get_addresses())
        try:
            result = upgrader.upgrade(self.image.file)
        except AbortedUpgrade:
            # this exception is raised when the checksum present on the image
            # equals the checksum of the image we are trying to flash, which
            # means the device was aleady flashed previously with the same image
            self.status = 'aborted'
            installed = True
        except Exception as e:
            upgrader.log(str(e))
            self.status = 'failed'
        else:
            installed = True
            self.status = 'success' if result else 'failed'
        self.log = '\n'.join(upgrader.log_lines)
        self.save()
        # if the firmware has been successfully installed,
        # or if it was already installed
        # set `instaleld` to `True` on the devicefirmware instance
        if installed:
            self.device.devicefirmware.installed = True
            self.device.devicefirmware.save(upgrade=False)

    def save(self, *args, **kwargs):
        result = super().save(*args, **kwargs)
        # when an operation is completed
        # trigger an update on the batch operation
        if self.batch and self.status != 'in-progress':
            self.batch.update()
        return result


@shared_task
def upgrade_firmware(operation_id):
    """
    Calls the ``upgrade()`` method of an
    ``UpgradeOperation`` instance in the background
    """
    operation = UpgradeOperation.objects.get(pk=operation_id)
    operation.upgrade()


@shared_task
def batch_upgrade_operation(build_id, firmwareless):
    """
    Calls the ``batch_upgrade()`` method of a
    ``Build`` instance in the background
    """
    build = Build.objects.get(pk=build_id)
    build.batch_upgrade(firmwareless=firmwareless)
