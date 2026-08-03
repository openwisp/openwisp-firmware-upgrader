from django.db import migrations
from django.db.models.signals import post_migrate

from openwisp_firmware_upgrader.tasks import queue_unconfirmed_extractions


def _queue_legacy_extractions(app_config, **kwargs):
    if app_config.name != "openwisp2.sample_firmware_upgrader":
        return
    post_migrate.disconnect(_queue_legacy_extractions)
    queue_unconfirmed_extractions.delay()


def backfill_firmware_image_status(apps, schema_editor):
    post_migrate.connect(_queue_legacy_extractions)


class Migration(migrations.Migration):
    dependencies = [
        ("sample_firmware_upgrader", "0007_alter_firmwareimage_compatible_and_more"),
    ]
    operations = [
        migrations.RunPython(
            backfill_firmware_image_status,
            reverse_code=migrations.RunPython.noop,
        )
    ]
