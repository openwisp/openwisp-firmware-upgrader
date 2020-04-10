from django.db import migrations
from django.contrib.auth.models import Permission

from . import create_default_permissions



def assign_permissions_to_groups(apps, schema_editor):
    app_label = 'firmware_upgrader'
    create_default_permissions(apps, schema_editor)
    Group = apps.get_model('openwisp_users', 'Group')

    try:
        admin = Group.objects.get(name='Administrator')
        operator = Group.objects.get(name='Operator')
    # consider failures custom cases
    # that do not have to be dealt with
    except Group.DoesNotExist:
        return

    operators_read_only_admins_manage = ['build', 'devicefirmware', 'firmwareimage', 'batchupgradeoperation', 'upgradeoperation']
    admins_can_manage = ['category']
    manage_operations = ['add', 'change', 'delete']

    for action in manage_operations:
        for model_name in admins_can_manage:
            permission = Permission.objects.get(
                codename='{}_{}'.format(action, model_name),
                content_type__app_label=app_label
            )
            admin.permissions.add(permission.pk)
    for model_name in operators_read_only_admins_manage:
        try:
            permission = Permission.objects.get(
                    codename='view_{}'.format(model_name),
                    content_type__app_label=app_label
            )
            operator.permissions.add(permission.pk)
        except Permission.DoesNotExist:
            pass
        for action in manage_operations:
            permission_ad = Permission.objects.get(
                    codename='{}_{}'.format(action, model_name),
                    content_type__app_label=app_label
            )
            admin.permissions.add(permission_ad.pk)


class Migration(migrations.Migration):

    dependencies = [
        ('firmware_upgrader', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(
            assign_permissions_to_groups,
            reverse_code=migrations.RunPython.noop
        )
    ]
