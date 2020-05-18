import logging
import os
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import models, transaction
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.module_loading import import_string
from django.utils.translation import ugettext_lazy as _
from private_storage.fields import PrivateFileField

from openwisp_controller.config.models import Device
from openwisp_users.mixins import OrgMixin
from openwisp_utils.base import TimeStampedEditableModel

from .. import settings as app_settings
from ..exceptions import (
    ReconnectionFailed,
    RecoverableFailure,
    UpgradeAborted,
    UpgradeNotNeeded,
)
from ..hardware import FIRMWARE_IMAGE_MAP, FIRMWARE_IMAGE_TYPE_CHOICES
from ..swapper import get_model_name, load_model
from ..tasks import upgrade_firmware

logger = logging.getLogger(__name__)


class AbstractCategory(OrgMixin, TimeStampedEditableModel):
    name = models.CharField(max_length=64, db_index=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name

    class Meta:
        abstract = True
        verbose_name = _('Firmware Category')
        verbose_name_plural = _('Firmware Categories')
        unique_together = ('name', 'organization')


class AbstractBuild(TimeStampedEditableModel):
    category = models.ForeignKey(
        get_model_name('Category'),
        on_delete=models.CASCADE,
        verbose_name=_('firmware category'),
        help_text=_(
            'if you have different firmware types '
            'eg: (BGP routers, wifi APs, DSL gateways) '
            'create a category for each.'
        ),
    )
    version = models.CharField(max_length=32, db_index=True)
    changelog = models.TextField(
        _('change log'),
        blank=True,
        help_text=_(
            'descriptive text indicating what '
            'has changed since the previous '
            'version, if applicable'
        ),
    )

    class Meta:
        abstract = True
        verbose_name = _('Firmware Build')
        verbose_name_plural = _('Firmware Builds')
        unique_together = ('category', 'version')
        ordering = ('-created',)

    def __str__(self):
        try:
            return f'{self.category} v{self.version}'
        except ObjectDoesNotExist:
            return super().__str__()

    def batch_upgrade(self, firmwareless):
        batch_model = load_model('BatchUpgradeOperation')
        batch = batch_model(build=self)
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
            image = self.firmwareimage_set.filter(type=device_fw.image.type).first()
            if image:
                device_fw.image = image
                device_fw.full_clean()
                device_fw.save(batch)

    def _find_related_device_firmwares(self, select_devices=False):
        related = ['image']
        if select_devices:
            related.append('device')
        return (
            load_model('DeviceFirmware')
            .objects.all()
            .select_related(*related)
            .filter(image__build__category_id=self.category_id)
            .exclude(image__build=self, installed=True)
        )

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
                df_model = load_model('DeviceFirmware')
                device_fw = df_model(device=device, image=image)
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
        return Device.objects.filter(
            devicefirmware__isnull=True,
            organization=self.category.organization,
            model__in=boards,
        )


def get_build_directory(instance, filename):
    build_pk = str(instance.build.pk)
    return '/'.join([build_pk, filename])


class AbstractFirmwareImage(TimeStampedEditableModel):
    build = models.ForeignKey(get_model_name('Build'), on_delete=models.CASCADE)
    file = PrivateFileField(
        'File', upload_to=get_build_directory, max_file_size=app_settings.MAX_FILE_SIZE
    )
    type = models.CharField(
        blank=True,
        max_length=128,
        choices=FIRMWARE_IMAGE_TYPE_CHOICES,
        help_text=_(
            'firmware image type: model or '
            'architecture. Leave blank to attempt '
            'determining automatically'
        ),
    )

    class Meta:
        abstract = True
        verbose_name = _('Firmware Image')
        verbose_name_plural = _('Firmware Images')
        unique_together = ('build', 'type')

    def __str__(self):
        if hasattr(self, 'build') and self.file.name:
            return f'{self.build}: {self.file.name}'
        return super().__str__()

    @property
    def boards(self):
        return FIRMWARE_IMAGE_MAP[self.type]['boards']

    def clean(self):
        self._clean_type()
        try:
            self.boards
        except KeyError:
            raise ValidationError({'type': 'Could not find boards for this type'})

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        self._remove_file()
        self._remove_empty_directory()

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

    def _remove_empty_directory(self):
        path = os.path.dirname(self.file.path)
        # TODO: precauton when migrating to private storage
        # avoid accidentally deleting the MEDIA_ROOT dir
        # remove this before or after first release
        is_media_root = Path(path).absolute() != Path(settings.MEDIA_ROOT).absolute()
        if not os.listdir(path) and is_media_root:
            os.rmdir(path)


class AbstractDeviceFirmware(TimeStampedEditableModel):
    device = models.OneToOneField('config.Device', on_delete=models.CASCADE)
    image = models.ForeignKey(get_model_name('FirmwareImage'), on_delete=models.CASCADE)
    installed = models.BooleanField(default=False)
    _old_image = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._update_old_image()

    class Meta:
        verbose_name = _('Device Firmware')
        abstract = True

    def clean(self):
        if self.image.build.category.organization != self.device.organization:
            raise ValidationError(
                {
                    'image': _(
                        'The organization of the image doesn\'t '
                        'match the organization of the device'
                    )
                }
            )
        if self.device.deviceconnection_set.count() < 1:
            raise ValidationError(
                _(
                    'This device does not have a related connection object defined '
                    'yet and therefore it would not be possible to upgrade it, '
                    'please add one in the section named "DEVICE CONNECTIONS"'
                )
            )
        if self.device.model not in self.image.boards:
            raise ValidationError(_('Device model and image model do not match'))

    @property
    def image_has_changed(self):
        return self._state.adding or self.image_id != self._old_image.id

    def save(self, batch=None, upgrade=True, *args, **kwargs):
        # if firwmare image has changed launch upgrade
        # upgrade won't be launched the first time
        if upgrade and (self.image_has_changed or not self.installed):
            self.installed = False
            super().save(*args, **kwargs)
            self.create_upgrade_operation(batch)
        else:
            super().save(*args, **kwargs)
        self._update_old_image()

    def _update_old_image(self):
        if hasattr(self, 'image'):
            self._old_image = self.image

    def create_upgrade_operation(self, batch):
        uo_model = load_model('UpgradeOperation')
        operation = uo_model(device=self.device, image=self.image)
        if batch:
            operation.batch = batch
        operation.full_clean()
        operation.save()
        # launch ``upgrade_firmware`` in the background (celery)
        # once changes are committed to the database
        transaction.on_commit(lambda: upgrade_firmware.delay(operation.pk))
        return operation


class AbstractBatchUpgradeOperation(TimeStampedEditableModel):
    build = models.ForeignKey(get_model_name('Build'), on_delete=models.CASCADE)
    STATUS_CHOICES = (
        ('in-progress', _('in progress')),
        ('success', _('completed successfully')),
        ('failed', _('completed with some failures')),
    )
    status = models.CharField(
        max_length=12, choices=STATUS_CHOICES, default=STATUS_CHOICES[0][0]
    )

    class Meta:
        abstract = True
        verbose_name = _('Mass upgrade operation')
        verbose_name_plural = _('Mass upgrade operations')

    def __str__(self):
        return f'Upgrade of {self.build} on {self.created}'

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
        return _(f'{completed} out of {self.total_operations}')

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
        result = Decimal(number) / Decimal(self.total_operations) * 100
        return round(result, 2)


class AbstractUpgradeOperation(TimeStampedEditableModel):
    STATUS_CHOICES = (
        ('in-progress', _('in progress')),
        ('success', _('success')),
        ('failed', _('failed')),
        ('aborted', _('aborted')),
    )
    device = models.ForeignKey('config.Device', on_delete=models.CASCADE)
    image = models.ForeignKey(get_model_name('FirmwareImage'), on_delete=models.CASCADE)
    status = models.CharField(
        max_length=12, choices=STATUS_CHOICES, default=STATUS_CHOICES[0][0]
    )
    log = models.TextField(blank=True)
    batch = models.ForeignKey(
        get_model_name('BatchUpgradeOperation'),
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )

    class Meta:
        abstract = True

    def log_line(self, line, save=True):
        if self.log:
            self.log += f'\n{line}'
        else:
            self.log = line
        logger.info(f'# {line}')
        if save:
            self.save()

    def upgrade(self, recoverable=True):
        conn = self.device.deviceconnection_set.first()
        installed = False
        if not conn:
            self.log_line('No device connection available')
            return
        # prevent multiple upgrade operations for
        # the same device running at the same time
        qs = (
            load_model('UpgradeOperation')
            .objects.filter(device=self.device, status='in-progress')
            .exclude(pk=self.pk)
        )
        if qs.count() > 0:
            message = 'Another upgrade operation is in progress, aborting...'
            logger.warn(message)
            self.log_line(message, save=False)
            self.status = 'aborted'
            self.save()
            return
        try:
            upgrader_class = app_settings.UPGRADERS_MAP[conn.update_strategy]
            upgrader_class = import_string(upgrader_class)
        except (AttributeError, ImportError) as e:
            logger.exception(e)
            return
        upgrader = upgrader_class(self, conn)
        try:
            upgrader.upgrade(self.image.file)
        # this exception is raised when the checksum present in the device
        # equals the checksum of the image we are trying to flash, which
        # means the device was aleady flashed previously with the same image
        except UpgradeNotNeeded:
            self.status = 'success'
            installed = True
        # this exception is raised when the test of the image fails,
        # meaning the image file is corrupted or not apt for flashing
        except UpgradeAborted:
            self.status = 'aborted'
        # raising this exception will cause celery to retry again
        # the upgrade according to its configuration
        except RecoverableFailure as e:
            cause = str(e)
            if recoverable:
                self.log_line(f'Detected a recoverable failure: {cause}.\n', save=False)
                self.log_line('The upgrade operation will be retried soon.')
                raise e
            self.status = 'failed'
            self.log_line(f'Max retries exceeded. Upgrade failed: {cause}.', save=False)
        # failure to reconnect to the device after reflashing or any
        # other unexpected exception will flag the upgrade as failed
        except (Exception, ReconnectionFailed) as e:
            cause = str(e)
            self.log_line(cause)
            self.status = 'failed'
            # if the reconnection failed we'll add some more info
            if isinstance(e, ReconnectionFailed):
                # update device connection info
                conn.is_working = False
                conn.failure_reason = cause
                conn.last_attempt = timezone.now()
                conn.save()
                # even if the reconnection failed,
                # the firmware image has been flashed
                installed = True
        # if no exception has been raised, the upgrade was successful
        else:
            installed = True
            self.status = 'success'
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
