import logging

from django.conf import settings
from django.db import migrations
from django.db.models import Value
from django.db.models.functions import Concat
from django.db.models.signals import post_migrate
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from openwisp_notifications.signals import notify

from openwisp_firmware_upgrader.hardware import OPENWRT_FIRMWARE_IMAGE_MAP
from openwisp_firmware_upgrader.swapper import load_model

logger = logging.getLogger(__name__)

_affected_pks = []
_recompute_build_ids = []


def _write_multi_board_log(FirmwareImage, image_type, boards):
    boards_str = ", ".join(boards)
    log_suffix = (
        "\n[!] Board could not be set automatically, this image is compatible "
        f"with multiple boards: {boards_str}. "
        "Please set the board field manually to match your devices."
    )
    candidate_pks = list(
        FirmwareImage.objects.filter(
            type=image_type, board="", extraction_status="unconfirmed"
        ).values_list("pk", flat=True)
    )
    if not candidate_pks:
        return 0
    FirmwareImage.objects.filter(pk__in=candidate_pks).update(
        extraction_log=Concat("extraction_log", Value(log_suffix)),
        extraction_status="failed",
        failure_reason="unsupported_format",
    )
    _affected_pks.extend(candidate_pks)
    return len(candidate_pks)


def _update_single_board(FirmwareImage, image_type, board, source):
    qs = FirmwareImage.objects.filter(
        type=image_type, board="", extraction_status="unconfirmed"
    )
    build_ids = list(qs.values_list("build_id", flat=True))
    if not build_ids:
        return
    qs.update(
        board=board,
        source=source,
        extraction_status="manually_confirmed",
    )
    _recompute_build_ids.extend(build_ids)


def _send_multi_board_notifications(app_config, **kwargs):
    if app_config.name != "openwisp_firmware_upgrader":
        return
    post_migrate.disconnect(_send_multi_board_notifications)
    FirmwareImage = load_model("FirmwareImage")
    Build = load_model("Build")
    affected = FirmwareImage.objects.filter(pk__in=_affected_pks).select_related(
        "build__category__organization"
    )
    affected_build_ids = set(_recompute_build_ids) | set(
        affected.values_list("build_id", flat=True)
    )
    for build in Build.objects.filter(pk__in=affected_build_ids):
        try:
            build.update_extraction_status()
        except Exception:
            logger.exception(
                "Failed to update extraction status for build %s", build.pk
            )
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
                "Failed to send multi-board reconcilation notification for image %s",
                image.pk,
            )


# imports OPENWRT_FIRMWARE_IMAGE_MAP from the deprecated hardware.py module
# on purpose. hardware.py is staying for now, so this is safe. When it is
# eventually removed, this migration must be updated first, or a fresh
# migrate from zero will break.
def backfill_board_from_hardware_map(apps, schema_editor):
    FirmwareImage = apps.get_model("firmware_upgrader", "FirmwareImage")
    has_multi_board_images = False
    _affected_pks.clear()
    _recompute_build_ids.clear()

    for image_type, info in OPENWRT_FIRMWARE_IMAGE_MAP.items():
        boards = info["boards"]
        if len(boards) == 1:
            _update_single_board(FirmwareImage, image_type, boards[0], "hardware map")
        else:
            if _write_multi_board_log(FirmwareImage, image_type, list(boards)):
                has_multi_board_images = True

    custom_images = getattr(settings, "OPENWISP_CUSTOM_OPENWRT_IMAGES", None)
    if custom_images:
        # accept a dict or a list of (image_type, info) pairs, the same
        # shape as FIRMWARE_IMAGE_TYPE_CHOICES in 0001_initial.py
        if not isinstance(custom_images, dict):
            custom_images = dict(custom_images)
        for image_type, info in custom_images.items():
            # unlike the hardware map, this comes from user config and may be
            # incomplete, so a missing 'boards" key is treated as no boards
            # rather than raising
            boards = info.get("boards", ())
            if len(boards) == 1:
                _update_single_board(
                    FirmwareImage, image_type, boards[0], "custom hardware map"
                )
            elif len(boards) > 1:
                if _write_multi_board_log(FirmwareImage, image_type, list(boards)):
                    has_multi_board_images = True
    if has_multi_board_images or _recompute_build_ids:
        post_migrate.connect(_send_multi_board_notifications)


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
