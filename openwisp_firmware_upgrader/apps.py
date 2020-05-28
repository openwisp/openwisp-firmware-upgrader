from django.apps import AppConfig
from django.conf import settings
from django.utils.translation import ugettext_lazy as _


class FirmwareUpdaterConfig(AppConfig):
    name = 'openwisp_firmware_upgrader'
    label = 'firmware_upgrader'
    verbose_name = _('Firmware Management')

    def ready(self, *args, **kwargs):
        self.add_default_menu_items()
        self.configure_drf_defaults()

    def add_default_menu_items(self):
        menu_setting = 'OPENWISP_DEFAULT_ADMIN_MENU_ITEMS'
        items = [
            {'model': f'{self.label}.Build'},
        ]
        if not hasattr(settings, menu_setting):  # pragma: no cover
            setattr(settings, menu_setting, items)
        else:
            current_menu = getattr(settings, menu_setting)
            current_menu += items

    def configure_drf_defaults(self):
        config = getattr(settings, 'REST_FRAMEWORK', {})
        config.setdefault('DEFAULT_THROTTLE_RATES', {})
        config['DEFAULT_THROTTLE_RATES'].setdefault('firmware_upgrader', '400/hour')
        setattr(settings, 'REST_FRAMEWORK', config)
