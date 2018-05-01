from django.apps import AppConfig
from django.utils.translation import ugettext_lazy as _


class FirmwareUpdaterConfig(AppConfig):
    name = 'openwisp_firmware_upgrader'
    label = 'firmware_upgrader'
    verbose_name = _('Firmware Management')
