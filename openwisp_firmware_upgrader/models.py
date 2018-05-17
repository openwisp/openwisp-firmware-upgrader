from __future__ import absolute_import, unicode_literals

import logging
import os

from celery import shared_task
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import models, transaction
from django.utils.encoding import python_2_unicode_compatible
from django.utils.module_loading import import_string
from django.utils.translation import ugettext_lazy as _

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
class Build(OrgMixin, TimeStampedEditableModel):
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    version = models.CharField(max_length=32, db_index=True)
    previous = models.ForeignKey('self', null=True, blank=True,
                                 on_delete=models.SET_NULL,
                                 verbose_name=_('previous build'),
                                 help_text=_('previous version of this build'))
    changelog = models.TextField(_('change log'), blank=True,
                                 help_text=_('descriptive text indicating what '
                                             'has changed since the previous '
                                             'version, if applicable'))

    class Meta:
        unique_together = ('category', 'version')

    def __str__(self):
        try:
            return '{0} v{1}'.format(self.category, self.version)
        except ObjectDoesNotExist:
            return super(Build, self).__str__()

    def upgrade_related_devices(self):
        qs = DeviceFirmware.objects.all().select_related('image')
        device_firmwares = qs.filter(image__build__category_id=self.category_id) \
                             .exclude(image__build=self)
        for device_firmware in device_firmwares:
            image = self.firmwareimage_set.filter(type=device_firmware.image.type).first()
            # if new image is found, upgrade device
            if image:
                device_firmware.image = image
                device_firmware.full_clean()
                device_firmware.save()


@python_2_unicode_compatible
class FirmwareImage(OrgMixin, TimeStampedEditableModel):
    build = models.ForeignKey(Build, on_delete=models.CASCADE)
    file = models.FileField()
    type = models.CharField(blank=True,
                            max_length=128,
                            choices=FIRMWARE_IMAGE_TYPE_CHOICES,
                            help_text=_('firmware image type'))

    class Meta:
        unique_together = ('build', 'type')

    def __str__(self):
        if hasattr(self, 'build') and self.file.name:
            return '{0}: {1}'.format(self.build, self.file.name)
        return super(FirmwareImage, self).__str__()

    def delete(self, *args, **kwargs):
        super(FirmwareImage, self).delete(*args, **kwargs)
        self._remove_file()

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
        if self.device.deviceconnection_set.count() < 1:
            raise ValidationError(
                _('This device does not have a related connection object defined '
                  'yet and therefore it would not be possible to upgrade it, '
                  'please add one in the section named "DEVICE CONNECTIONS"')
            )

    def save(self, *args, **kwargs):
        # if firwmare image has changed launch upgrade
        # upgrade won't be launched the first time
        if self._old_image is not None and self.image_id != self._old_image.id:
            self.installed = False
            super(DeviceFirmware, self).save(*args, **kwargs)
            self.create_upgrade_operation()
        else:
            super(DeviceFirmware, self).save(*args, **kwargs)
        self._update_old_image()

    def _update_old_image(self):
        if hasattr(self, 'image'):
            self._old_image = self.image

    def create_upgrade_operation(self):
        operation = UpgradeOperation(device=self.device,
                                     image=self.image)
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
class UpgradeOperation(TimeStampedEditableModel):
    STATUS_CHOICES = (
        ('in-progress', _('in progress')),
        ('success', _('success')),
        ('failed', _('failed')),
        ('aborted', _('aborted')),
    )
    device = models.ForeignKey('config.Device', on_delete=models.CASCADE)
    image = models.ForeignKey(FirmwareImage, on_delete=models.CASCADE)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES,
                              default=STATUS_CHOICES[0][0])
    log = models.TextField(blank=True)

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
            self.device.devicefirmware.save()


@shared_task
def upgrade_firmware(operation_id):
    """
    Calls the ``upgrade()`` method of an
    ``UpgradeOperation`` instance in the background
    """
    operation = UpgradeOperation.objects.get(pk=operation_id)
    operation.upgrade()
