from django.db import migrations

from openwisp_firmware_upgrader.hardware import OPENWRT_FIRMWARE_IMAGE_MAP


def backfill_board_from_hardware_map(apps, schema_editor):
    FirmwareImage = apps.get_model("firmware_upgrader", "FirmwareImage")

    for image_type, info in OPENWRT_FIRMWARE_IMAGE_MAP.items():
        boards = info.get("boards", ())
        if not boards:
            continue
        FirmwareImage.objects.filter(
            type=image_type,
            board="",
        ).update(board=boards[0], source="hardware map")


class Migration(migrations.Migration):
    dependencies = [
        ("firmware_upgrader", "0022_alter_firmwareimage_compatible"),
    ]

    operations = [
        migrations.RunPython(
            backfill_board_from_hardware_map,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
