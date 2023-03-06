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
        'data-schema-selector': '#devicefirmware-0-upgrade_options',
        'data-show-errors': 'never',
        'class': 'manual',
    }

    @property
    def media(self):
        media = super().media
        js = [
            'admin/js/jquery.init.js',
            'firmware-upgrader/js/device-firmware.js',
        ] + list(media._js)
        css = media._css.copy()
        css['all'] += ['firmware-upgrader/css/device-firmware.css']
        return forms.Media(js=js, css=css)
