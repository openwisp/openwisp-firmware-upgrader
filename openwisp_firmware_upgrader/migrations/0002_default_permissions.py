from django.db import migrations

from . import create_permissions_for_default_groups


def create_permissions_for_default_groups_helper(apps, schema_editor):
    app_label = 'firmware_upgrader'
    create_permissions_for_default_groups(apps, schema_editor, app_label)


class Migration(migrations.Migration):

    dependencies = [
        ('firmware_upgrader', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(
            create_permissions_for_default_groups_helper,
            reverse_code=migrations.RunPython.noop,
        )
    ]
