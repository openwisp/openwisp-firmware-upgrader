from django import forms
from django.utils.translation import gettext_lazy as _

from openwisp_controller.config.widgets import JsonSchemaWidget as BaseJsonSchemaWidget

from .swapper import load_model

UpgradeOperation = load_model("UpgradeOperation")
DeviceFirmware = load_model("DeviceFirmware")


class FirmwareSchemaWidget(BaseJsonSchemaWidget):
    schema_view_name = None
    app_label_model = (
        f"{UpgradeOperation._meta.app_label}_{UpgradeOperation._meta.model_name}"
    )
    netjsonconfig_hint = False
    advanced_mode = False
    extra_attrs = {
        "data-show-errors": "never",
        "class": "manual",
    }

    @property
    def media(self):
        return super().media + forms.Media(
            css={"all": ["firmware-upgrader/css/upgrade-options.css"]}
        )


class MassUpgradeSelect2Widget(forms.Select):
    """
    Custom Select2 widget for mass upgrade operations (groups and locations).
    """

    def __init__(self, attrs=None, placeholder=None):
        if placeholder is None:
            placeholder = _("Select an option")
        default_attrs = {
            "class": "select2-input",
            "data-placeholder": placeholder,
            "data-allow-clear": "true",
        }
        if attrs:
            default_attrs.update(attrs)
        super().__init__(attrs=default_attrs)

    @property
    def media(self):
        return super().media + forms.Media(
            js=[
                "admin/js/jquery.init.js",
                "firmware-upgrader/js/mass-upgrade-select2.js",
            ],
            css={
                "all": [
                    "admin/css/vendor/select2/select2.min.css",
                    "admin/css/autocomplete.css",
                    "admin/css/ow-auto-filter.css",
                ]
            },
        )
