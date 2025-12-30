from django.db import migrations

from . import update_image_types_forward, update_image_types_reverse


def update_image_types_forward_helper(apps, schema_editor):
    app_label = "firmware_upgrader"
    update_image_types_forward(apps, schema_editor, app_label)


def update_image_types_reverse_helper(apps, schema_editor):
    app_label = "firmware_upgrader"
    update_image_types_reverse(apps, schema_editor, app_label)


class Migration(migrations.Migration):
    dependencies = [
        ("firmware_upgrader", "0011_alter_category_organization"),
    ]

    operations = [
        migrations.RunPython(
            update_image_types_forward_helper,
            reverse_code=update_image_types_reverse_helper,
        ),
    ]
