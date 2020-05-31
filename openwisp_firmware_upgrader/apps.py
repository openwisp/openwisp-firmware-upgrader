from django.conf import settings
from django.utils.translation import ugettext_lazy as _

from openwisp_utils.api.apps import ApiAppConfig
from openwisp_utils.utils import default_or_test

from . import settings as app_settings


class FirmwareUpdaterConfig(ApiAppConfig):
    name = 'openwisp_firmware_upgrader'
    label = 'firmware_upgrader'
    verbose_name = _('Firmware Management')

    API_ENABLED = app_settings.FIRMWARE_UPGRADER_API
    REST_FRAMEWORK_SETTINGS = {
        'DEFAULT_THROTTLE_RATES': {
            'firmware_upgrader': default_or_test('400/hour', None)
        },
    }

    def ready(self, *args, **kwargs):
        super().ready(*args, **kwargs)
        self.add_default_menu_items()

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
