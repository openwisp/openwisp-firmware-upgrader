from django.db.models.signals import post_save
from django.utils.translation import gettext_lazy as _
from swapper import get_model_name, load_model

from openwisp_utils.admin_theme.menu import register_menu_group
from openwisp_utils.api.apps import ApiAppConfig
from openwisp_utils.utils import default_or_test

from . import settings as app_settings


class FirmwareUpdaterConfig(ApiAppConfig):
    name = 'openwisp_firmware_upgrader'
    label = 'firmware_upgrader'
    verbose_name = _('Firmware Management')
    default_auto_field = 'django.db.models.AutoField'

    API_ENABLED = app_settings.FIRMWARE_UPGRADER_API
    REST_FRAMEWORK_SETTINGS = {
        'DEFAULT_THROTTLE_RATES': {
            'firmware_upgrader': default_or_test('1000/minute', None)
        },
    }

    def ready(self, *args, **kwargs):
        super().ready(*args, **kwargs)
        self.register_menu_groups()
        self.connect_device_signals()

    def register_menu_groups(self):
        register_menu_group(
            position=100,
            config={
                'label': _('Firmware'),
                'items': {
                    1: {
                        'label': _('Builds'),
                        'model': get_model_name(self.label, 'Build'),
                        'name': 'changelist',
                        'icon': 'ow-build',
                    },
                    2: {
                        'label': _('Categories'),
                        'model': get_model_name(self.label, 'Category'),
                        'name': 'changelist',
                        'icon': 'ow-category',
                    },
                    3: {
                        'label': _('Mass Upgrade Operations'),
                        'model': get_model_name(self.label, 'BatchUpgradeOperation'),
                        'name': 'changelist',
                        'icon': 'ow-mass-upgrade',
                    },
                },
                'icon': 'ow-firmware',
            },
        )

    def connect_device_signals(self):
        DeviceConnection = load_model('connection', 'DeviceConnection')
        DeviceFirmware = load_model('firmware_upgrader', 'DeviceFirmware')
        FirmwareImage = load_model('firmware_upgrader', 'FirmwareImage')
        post_save.connect(
            DeviceFirmware.auto_add_device_firmware_to_device,
            sender=DeviceConnection,
            dispatch_uid='connection.auto_add_device_firmware',
        )
        post_save.connect(
            DeviceFirmware.auto_create_device_firmwares,
            sender=FirmwareImage,
            dispatch_uid='firmware_image.auto_add_device_firmwares',
        )
