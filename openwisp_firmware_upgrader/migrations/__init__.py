from django.contrib.auth.management import create_permissions
from django.contrib.auth.models import Permission
from swapper import load_model

DeviceConnection = load_model("connection", "DeviceConnection")
DeviceFirmware = load_model("firmware_upgrader", "DeviceFirmware")


def create_default_permissions(apps, schema_editor):
    for app_config in apps.get_app_configs():
        app_config.models_module = True
        create_permissions(app_config, apps=apps, verbosity=0)
        app_config.models_module = None


def create_permissions_for_default_groups(apps, schema_editor, app_label):
    create_default_permissions(apps, schema_editor)
    Group = apps.get_model("openwisp_users", "Group")

    try:
        admin = Group.objects.get(name="Administrator")
        operator = Group.objects.get(name="Operator")
    # consider failures custom cases
    # that do not have to be dealt with
    except Group.DoesNotExist:
        return

    operators_read_only_admins_manage = [
        "build",
        "devicefirmware",
        "firmwareimage",
        "batchupgradeoperation",
        "upgradeoperation",
    ]
    admins_can_manage = ["category"]
    manage_operations = ["add", "change", "delete", "view"]

    for action in manage_operations:
        for model_name in admins_can_manage:
            permission = Permission.objects.get(
                codename="{}_{}".format(action, model_name),
                content_type__app_label=app_label,
            )
            admin.permissions.add(permission.pk)
    for model_name in operators_read_only_admins_manage:
        try:
            permission = Permission.objects.get(
                codename="view_{}".format(model_name), content_type__app_label=app_label
            )
            operator.permissions.add(permission.pk)
        except Permission.DoesNotExist:
            pass
        for action in manage_operations:
            permission = Permission.objects.get(
                codename="{}_{}".format(action, model_name),
                content_type__app_label=app_label,
            )
            admin.permissions.add(permission.pk)


def create_device_firmware_for_connections(apps, schema_editor, app_label):
    for device_connection in DeviceConnection.objects.all():
        DeviceFirmware.create_for_device(device_connection.device)


# Mapping of old image type identifiers to new ones
IMAGE_TYPE_MAPPING = {
    "octeon-erlite-squashfs-sysupgrade.tar": "octeon-generic-ubnt_edgerouter-lite-squashfs-sysupgrade.tar",
    "ath79-generic-ubnt_unifi-squashfs-sysupgrade.bin": "ath79-generic-ubnt_unifi-ap-squashfs-sysupgrade.bin",
    "x86-generic-combined-squashfs.img.gz": "x86-generic-generic-squashfs-combined.img.gz",
    "x86-geode-combined-squashfs.img.gz": "x86-geode-generic-squashfs-combined.img.gz",
}

# Reverse mapping for rollback
REVERSE_IMAGE_TYPE_MAPPING = {v: k for k, v in IMAGE_TYPE_MAPPING.items()}


def update_image_types_forward(apps, schema_editor, app_label):
    """
    Updates firmware image type identifiers from old values to new values.
    """
    FirmwareImage = apps.get_model(app_label, "FirmwareImage")
    for old_type, new_type in IMAGE_TYPE_MAPPING.items():
        FirmwareImage.objects.filter(type=old_type).update(type=new_type)


def update_image_types_reverse(apps, schema_editor, app_label):
    """
    Reverts firmware image type identifiers from new values back to old values.
    """
    FirmwareImage = apps.get_model(app_label, "FirmwareImage")
    for new_type, old_type in REVERSE_IMAGE_TYPE_MAPPING.items():
        FirmwareImage.objects.filter(type=new_type).update(type=old_type)
