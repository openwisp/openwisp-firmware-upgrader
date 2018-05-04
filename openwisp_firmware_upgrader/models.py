import logging
import os

from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.utils.encoding import python_2_unicode_compatible
from django.utils.translation import ugettext_lazy as _

from openwisp_users.mixins import OrgMixin
from openwisp_utils.base import TimeStampedEditableModel

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

    def __str__(self):
        try:
            return '{0} v{1}'.format(self.category, self.version)
        except ObjectDoesNotExist:
            return super(Build, self).__str__()

    class Meta:
        unique_together = ('category', 'version')


@python_2_unicode_compatible
class FirmwareImage(OrgMixin, TimeStampedEditableModel):
    build = models.ForeignKey(Build, on_delete=models.CASCADE)
    file = models.FileField()
    models = models.TextField(blank=True,
                              help_text=_('hardware models this image '
                                          'refers to, one per line'))

    class Meta:
        unique_together = ('build', 'models')

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
    device = models.OneToOneField('config.Device', on_delete=models.CASCADE)
    image = models.ForeignKey(FirmwareImage, on_delete=models.CASCADE)
    installed = models.BooleanField(default=False)
    _old_image = None

    def __init__(self, *args, **kwargs):
        super(DeviceFirmware, self).__init__(*args, **kwargs)
        self._update_old_image()

    def save(self, *args, **kwargs):
        # if firwmare image has changed launch upgrade
        # upgrade won't be launched the first time
        if self._old_image is not None and self.image != self._old_image:
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
        upgrade = UpgradeOperation(device=self.device,
                                   image=self.image)
        upgrade.full_clean()
        upgrade.save()


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

    def save(self, *args, **kwargs):
        # determine if new object
        if self._state.adding:
            is_new = True
        else:
            is_new = False
        # save
        super(UpgradeOperation, self).save(*args, **kwargs)
        # perform upgrades only for new operations
        if is_new:
            self.upgrade()

    def upgrade(self):
        pass
