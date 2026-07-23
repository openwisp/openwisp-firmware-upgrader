from django.conf import settings
from django.db import migrations

from openwisp_firmware_upgrader.hardware import OPENWRT_FIRMWARE_IMAGE_MAP


def _write_multi_board_log(FirmwareImage, image_type, boards):
    boards_str = ", ".join(boards)
    log_suffix = (
        "\n[!] Board could not be set automatically, this image is compatible "
        f"with multiple boards: {boards_str}. "
        "Please set the board field manually to match your devices."
    )
    for image in FirmwareImage.objects.filter(type=image_type, board=""):
        image.extraction_log = (image.extraction_log or "") + log_suffix
        image.save(update_fields=["extraction_log"])


def backfill_board_from_hardware_map(apps, schema_editor):
    FirmwareImage = apps.get_model("firmware_upgrader", "FirmwareImage")
    for image_type, info in OPENWRT_FIRMWARE_IMAGE_MAP.items():
        boards = info["boards"]
        if len(boards) == 1:
            FirmwareImage.objects.filter(
                type=image_type,
                board="",
            ).update(board=boards[0], source="hardware map")
        else:
            _write_multi_board_log(FirmwareImage, image_type, list(boards))

    custom_images = getattr(settings, "OPENWISP_CUSTOM_OPENWRT_IMAGES", None)
    if custom_images:
        if not isinstance(custom_images, dict):
            custom_images = dict(custom_images)
        for image_type, info in custom_images.items():
            boards = info.get("boards", ())
            if len(boards) == 1:
                FirmwareImage.objects.filter(
                    type=image_type,
                    board="",
                ).update(board=boards[0], source="custom hardware map")
            elif len(boards) > 1:
                _write_multi_board_log(FirmwareImage, image_type, list(boards))


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
