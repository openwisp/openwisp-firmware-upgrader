from django import forms

from openwisp_controller.config.widgets import JsonSchemaWidget as BaseJsonSchemaWidget

from .swapper import load_model

UpgradeOperation = load_model('UpgradeOperation')
DeviceFirmware = load_model('DeviceFirmware')


class FirmwareSchemaWidget(BaseJsonSchemaWidget):
    schema_view_name = None
    app_label_model = (
        f'{UpgradeOperation._meta.app_label}_{UpgradeOperation._meta.model_name}'
    )
    netjsonconfig_hint = False
    advanced_mode = False
    extra_attrs = {
        'data-show-errors': 'never',
        'class': 'manual',
    }

    @property
    def media(self):
        return super().media + forms.Media(
            css={'all': ['firmware-upgrader/css/upgrade-options.css']}
        )
