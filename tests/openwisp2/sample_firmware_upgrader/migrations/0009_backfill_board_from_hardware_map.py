import logging

from django.conf import settings
from django.db import migrations
from django.db.models.signals import post_migrate
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from openwisp_notifications.signals import notify

from openwisp_firmware_upgrader.hardware import OPENWRT_FIRMWARE_IMAGE_MAP
from openwisp_firmware_upgrader.swapper import load_model

logger = logging.getLogger(__name__)


def _write_multi_board_log(FirmwareImage, image_type, boards):
    boards_str = ", ".join(boards)
    log_suffix = (
        "\n[!] Board could not be set automatically, this image is compatible "
        f"with multiple boards: {boards_str}. "
        "Please set the board field manually to match your devices."
    )
    affected_pks = []
    for image in FirmwareImage.objects.filter(type=image_type, board=""):
        image.extraction_log = (image.extraction_log or "") + log_suffix
        image.save(update_fields=["extraction_log"])
        affected_pks.append(image.pk)
    if affected_pks:
        FirmwareImage.objects.filter(pk__in=affected_pks).update(
            extraction_status="failed"
        )
    return len(affected_pks)


def _send_multi_board_notifications(app_config, **kwargs):
    if app_config.name != "openwisp2.sample_firmware_upgrader":
        return
    post_migrate.disconnect(_send_multi_board_notifications)
    FirmwareImage = load_model("FirmwareImage")
    Build = load_model("Build")
    affected = FirmwareImage.objects.filter(
        extraction_status="failed",
        extraction_log__contains="compatible with multiple boards",
    ).select_related("build__category__organization")
    affected_build_ids = affected.values_list("build_id", flat=True).distinct()
    for build in Build.objects.filter(pk__in=affected_build_ids):
        build._update_extraction_status()
    for image in affected:
        org = image.build.category.organization
        notify_sender = org if org is not None else image
        opts = image._meta
        admin_url = (
            reverse(
                f"admin:{opts.app_label}_{opts.model_name}_change",
                args=[str(image.pk)],
            )
            + "#device-metadata"
        )
        try:
            notify.send(
                sender=notify_sender,
                type="generic_message",
                level="warning",
                url=admin_url,
                target=image,
                message=format_html(
                    _(
                        "Board could not be set automatically for "
                        '<a href="{url}">{image}</a>. '
                        "This image is compatible with multiple boards. "
                        "Please set the board field manually to match your devices."
                    ),
                    url=admin_url,
                    image=image,
                ),
            )
        except Exception:
            logger.exception(
                "Failed to send multi-board reconciliation notification for image %s",
                image.pk,
            )


def backfill_board_from_hardware_map(apps, schema_editor):
    FirmwareImage = apps.get_model("sample_firmware_upgrader", "FirmwareImage")
    has_multi_board_images = False

    for image_type, info in OPENWRT_FIRMWARE_IMAGE_MAP.items():
        boards = info["boards"]
        if len(boards) == 1:
            FirmwareImage.objects.filter(
                type=image_type,
                board="",
            ).update(board=boards[0], source="hardware map")
        else:
            if _write_multi_board_log(FirmwareImage, image_type, list(boards)):
                has_multi_board_images = True

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
                if _write_multi_board_log(FirmwareImage, image_type, list(boards)):
                    has_multi_board_images = True
    if has_multi_board_images:
        post_migrate.connect(_send_multi_board_notifications)


class Migration(migrations.Migration):
    dependencies = [
        ("sample_firmware_upgrader", "0008_backfill_extraction_status"),
    ]
    operations = [
        migrations.RunPython(
            backfill_board_from_hardware_map,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
