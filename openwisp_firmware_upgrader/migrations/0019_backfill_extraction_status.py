from django.db import migrations


def backfill_firmware_image_status(apps, schema_editor):
    FirmwareImage = apps.get_model("firmware_upgrader", "FirmwareImage")
    FirmwareImage.objects.filter(extraction_status="unconfirmed").update(
        extraction_status="manually_confirmed",
        source="manual",
    )


def backfill_build_status(apps, schema_editor):
    Build = apps.get_model("firmware_upgrader", "Build")
    Build.objects.filter(status="analyzing").update(status="manually_confirmed")


class Migration(migrations.Migration):
    dependencies = [
        ("firmware_upgrader", "0018_build_status_firmwareimage_board_and_more"),
    ]
    operations = [
        migrations.RunPython(
            backfill_firmware_image_status,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.RunPython(
            backfill_build_status,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
