from django.contrib.auth.models import Permission

from django.contrib.auth.management import create_permissions

from swapper import load_model


DeviceConnection = load_model('connection', 'DeviceConnection')
DeviceFirmware = load_model('firmware_upgrader', 'DeviceFirmware')


def create_default_permissions(apps, schema_editor):
    for app_config in apps.get_app_configs():
        app_config.models_module = True
        create_permissions(app_config, apps=apps, verbosity=0)
        app_config.models_module = None


def create_permissions_for_default_groups(apps, schema_editor, app_label):
    create_default_permissions(apps, schema_editor)
    Group = apps.get_model('openwisp_users', 'Group')

    try:
        admin = Group.objects.get(name='Administrator')
        operator = Group.objects.get(name='Operator')
    # consider failures custom cases
    # that do not have to be dealt with
    except Group.DoesNotExist:
        return

    operators_read_only_admins_manage = [
        'build',
        'devicefirmware',
        'firmwareimage',
        'batchupgradeoperation',
        'upgradeoperation',
    ]
    admins_can_manage = ['category']
    manage_operations = ['add', 'change', 'delete']

    for action in manage_operations:
        for model_name in admins_can_manage:
            permission = Permission.objects.get(
                codename='{}_{}'.format(action, model_name),
                content_type__app_label=app_label,
            )
            admin.permissions.add(permission.pk)
    for model_name in operators_read_only_admins_manage:
        try:
            permission = Permission.objects.get(
                codename='view_{}'.format(model_name), content_type__app_label=app_label
            )
            operator.permissions.add(permission.pk)
        except Permission.DoesNotExist:
            pass
        for action in manage_operations:
            permission = Permission.objects.get(
                codename='{}_{}'.format(action, model_name),
                content_type__app_label=app_label,
            )
            admin.permissions.add(permission.pk)


def create_device_firmware_for_connections(apps, schema_editor, app_label):
    for device_connection in DeviceConnection.objects.all():
        DeviceFirmware.create_for_device(device_connection.device)
