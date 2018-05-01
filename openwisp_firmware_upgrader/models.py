from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.utils.encoding import python_2_unicode_compatible
from django.utils.translation import ugettext_lazy as _

from openwisp_users.mixins import OrgMixin
from openwisp_utils.base import TimeStampedEditableModel


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

    def __str__(self):
        if hasattr(self, 'build') and self.file.name:
            return '{0}: {1}'.format(self.build, self.file.name)
        return super(FirmwareImage, self).__str__()

    class Meta:
        unique_together = ('build', 'models')


@python_2_unicode_compatible
class DeviceFirmware(TimeStampedEditableModel):
    device = models.OneToOneField('config.Device', on_delete=models.CASCADE)
    image = models.ForeignKey(FirmwareImage, on_delete=models.CASCADE)
    installed = models.BooleanField(default=False)
