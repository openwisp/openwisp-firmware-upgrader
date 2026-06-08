from django.db.models.signals import post_save, pre_delete
from django.utils.translation import gettext_lazy as _
from openwisp_notifications.types import register_notification_type
from swapper import get_model_name, load_model

from openwisp_utils.admin_theme.menu import register_menu_group
from openwisp_utils.api.apps import ApiAppConfig
from openwisp_utils.utils import default_or_test

from . import settings as app_settings
from .websockets import BatchUpgradeProgressPublisher, UpgradeProgressPublisher


class FirmwareUpdaterConfig(ApiAppConfig):
    name = "openwisp_firmware_upgrader"
    label = "firmware_upgrader"
    verbose_name = _("Firmware Management")
    default_auto_field = "django.db.models.AutoField"

    API_ENABLED = app_settings.FIRMWARE_UPGRADER_API
    REST_FRAMEWORK_SETTINGS = {
        "DEFAULT_THROTTLE_RATES": {
            "firmware_upgrader": default_or_test("1000/minute", None)
        },
    }

    def ready(self, *args, **kwargs):
        super().ready(*args, **kwargs)
        self.register_menu_groups()
        self.register_notification_types()
        self.connect_device_signals()
        self.connect_upgrade_signals()
        self.connect_delete_signals()
        self.connect_monitoring_signals()

    def register_menu_groups(self):
        register_menu_group(
            position=100,
            config={
                "label": _("Firmware"),
                "items": {
                    1: {
                        "label": _("Builds"),
                        "model": get_model_name(self.label, "Build"),
                        "name": "changelist",
                        "icon": "ow-build",
                    },
                    2: {
                        "label": _("Categories"),
                        "model": get_model_name(self.label, "Category"),
                        "name": "changelist",
                        "icon": "ow-category",
                    },
                    3: {
                        "label": _("Mass Upgrade Operations"),
                        "model": get_model_name(self.label, "BatchUpgradeOperation"),
                        "name": "changelist",
                        "icon": "ow-mass-upgrade",
                    },
                },
                "icon": "ow-firmware",
            },
        )

    def register_notification_types(self):
        BatchUpgradeOperation = load_model("firmware_upgrader", "BatchUpgradeOperation")
        UpgradeOperation = load_model("firmware_upgrader", "UpgradeOperation")
        Device = load_model("config", "Device")
        register_notification_type(
            "pending_upgrade_reminder",
            {
                "verbose_name": _("Pending Firmware Upgrade Reminder"),
                "verb": _("still pending"),
                "level": "info",
                "email_subject": _(
                    "[{site.name}] Pending firmware upgrades in mass upgrade "
                    "{notification.target}"
                ),
                "message": "{notification.description}",
            },
            models=[BatchUpgradeOperation],
        )
        register_notification_type(
            "persistent_upgrade_failed",
            {
                "verbose_name": _("Persistent Firmware Upgrade Failed"),
                "verb": _("failed"),
                "level": "error",
                "email_subject": _(
                    "[{site.name}] Persistent firmware upgrade FAILED for device "
                    "{notification.target}"
                ),
                "message": "{notification.description}",
            },
            models=[UpgradeOperation, Device],
        )

    def connect_device_signals(self):
        DeviceConnection = load_model("connection", "DeviceConnection")
        DeviceFirmware = load_model("firmware_upgrader", "DeviceFirmware")
        FirmwareImage = load_model("firmware_upgrader", "FirmwareImage")

        post_save.connect(
            DeviceFirmware.auto_add_device_firmware_to_device,
            sender=DeviceConnection,
            dispatch_uid="connection.auto_add_device_firmware",
        )
        post_save.connect(
            DeviceFirmware.auto_create_device_firmwares,
            sender=FirmwareImage,
            dispatch_uid="firmware_image.auto_add_device_firmwares",
        )

    def connect_upgrade_signals(self):
        UpgradeOperation = load_model("firmware_upgrader", "UpgradeOperation")
        BatchUpgradeOperation = load_model("firmware_upgrader", "BatchUpgradeOperation")

        post_save.connect(
            UpgradeProgressPublisher.handle_upgrade_operation_post_save,
            sender=UpgradeOperation,
            dispatch_uid="upgrade_operation.websocket_publish",
        )
        post_save.connect(
            BatchUpgradeProgressPublisher.handle_batch_upgrade_operation_saved,
            sender=BatchUpgradeOperation,
            dispatch_uid="batch_upgrade_operation.websocket_publish",
        )
        post_save.connect(
            UpgradeOperation.notify_on_failed_persistent_upgrade,
            sender=UpgradeOperation,
            dispatch_uid="upgrade_operation.notify_on_failure",
        )

    def connect_delete_signals(self):
        """
        Connect signals for handling firmware file deletion
        when related models are deleted.
        """
        Build = load_model("firmware_upgrader", "Build")
        Category = load_model("firmware_upgrader", "Category")
        Organization = load_model("openwisp_users", "Organization")
        FirmwareImage = load_model("firmware_upgrader", "FirmwareImage")

        pre_delete.connect(
            FirmwareImage.build_pre_delete_handler,
            sender=Build,
            dispatch_uid="build.pre_delete.firmware_files",
        )
        pre_delete.connect(
            FirmwareImage.category_pre_delete_handler,
            sender=Category,
            dispatch_uid="category.pre_delete.firmware_files",
        )
        pre_delete.connect(
            FirmwareImage.organization_pre_delete_handler,
            sender=Organization,
            dispatch_uid="organization.pre_delete.firmware_files",
        )

    def connect_monitoring_signals(self):
        """
        Connect the openwisp-monitoring health_status_changed signal so
        pending upgrades wake up when a device recovers.
        """
        try:
            from openwisp_monitoring.device.signals import health_status_changed
        except ModuleNotFoundError as error:
            if error.name not in (
                "openwisp_monitoring",
                "openwisp_monitoring.device",
                "openwisp_monitoring.device.signals",
            ):
                raise
            return
        UpgradeOperation = load_model("firmware_upgrader", "UpgradeOperation")
        health_status_changed.connect(
            UpgradeOperation.handle_health_status_changed,
            dispatch_uid="firmware_upgrader.health_status_changed",
        )


del ApiAppConfig
