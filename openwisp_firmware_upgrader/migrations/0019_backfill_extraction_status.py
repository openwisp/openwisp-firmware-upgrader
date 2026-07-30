from django.db import migrations
from django.db.models.signals import post_migrate

from openwisp_firmware_upgrader.swapper import load_model
from openwisp_firmware_upgrader.tasks import extract_firmware_metadata


def _queue_legacy_extractions(app_config, **kwargs):
    if app_config.name != "openwisp_firmware_upgrader":
        return
    post_migrate.disconnect(_queue_legacy_extractions)
    FirmwareImage = load_model("FirmwareImage")
    pks = list(
        FirmwareImage.objects.filter(extraction_status="unconfirmed").values_list(
            "pk", flat=True
        )
    )
    for pk in pks:
        extract_firmware_metadata.delay(pk)


def backfill_firmware_image_status(apps, schema_editor):
    post_migrate.connect(_queue_legacy_extractions)


class Migration(migrations.Migration):
    dependencies = [
        ("firmware_upgrader", "0018_build_status_firmwareimage_board_and_more"),
    ]
    operations = [
        migrations.RunPython(
            backfill_firmware_image_status,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
