import functools
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

_DISPATCH_UID = "sample_firmware_upgrader.0009_multi_board_notify"


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
        return []
    FirmwareImage.objects.filter(pk__in=candidate_pks).update(
        extraction_log=Concat("extraction_log", Value(log_suffix)),
        extraction_status="incomplete",
    )
    return candidate_pks


def _update_single_board(FirmwareImage, image_type, board, source):
    qs = FirmwareImage.objects.filter(
        type=image_type, board="", extraction_status="unconfirmed"
    )
    build_ids = list(qs.values_list("build_id", flat=True))
    if not build_ids:
        return []
    qs.update(
        board=board,
        source=source,
        extraction_status="manually_confirmed",
    )
    return build_ids


def _compute_build_status(FirmwareImage, build_id, current_status):
    analyzing = {"unconfirmed", "in_progress"}
    final_statuses = {
        "success",
        "incomplete",
        "failed",
        "invalid",
        "manually_confirmed",
    }
    statuses = set(
        FirmwareImage.objects.filter(build_id=build_id).values_list(
            "extraction_status", flat=True
        )
    )
    if not statuses:
        return None
    # a leftover unrelated image still sitting at unconfirmed/in_progress
    # must not downgrade a build that has already reached a final status
    if statuses & analyzing and current_status in final_statuses:
        return None
    if statuses & analyzing:
        return "analyzing"
    if "invalid" in statuses:
        return "invalid"
    if "failed" in statuses:
        return "failed"
    if "incomplete" in statuses:
        return "incomplete"
    if "manually_confirmed" in statuses:
        return "manually_confirmed"
    return "success"


def _send_multi_board_notifications(app_config, affected_pks, **kwargs):
    if app_config.name != "openwisp2.sample_firmware_upgrader":
        return
    post_migrate.disconnect(dispatch_uid=_DISPATCH_UID)
    # this handler runs after every migration has completed, so it's safe
    # to use the live model here, unlike inside the migration function
    FirmwareImage = load_model("FirmwareImage")
    affected = FirmwareImage.objects.filter(pk__in=affected_pks).select_related(
        "build__category__organization"
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
    FirmwareImage = apps.get_model("sample_firmware_upgrader", "FirmwareImage")
    Build = apps.get_model("sample_firmware_upgrader", "Build")
    affected_pks = []
    recompute_build_ids = []

    for image_type, info in OPENWRT_FIRMWARE_IMAGE_MAP.items():
        boards = info["boards"]
        if len(boards) == 1:
            recompute_build_ids.extend(
                _update_single_board(
                    FirmwareImage, image_type, boards[0], "hardware map"
                )
            )
        else:
            affected_pks.extend(
                _write_multi_board_log(FirmwareImage, image_type, list(boards))
            )

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
                recompute_build_ids.extend(
                    _update_single_board(
                        FirmwareImage, image_type, boards[0], "custom hardware map"
                    )
                )
            elif len(boards) > 1:
                affected_pks.extend(
                    _write_multi_board_log(FirmwareImage, image_type, list(boards))
                )
    # build status recomputed here, not in post_migrate below: MigrationExecutor.migrate()
    # never emits post_migrate, which would leave builds stuck stale
    affected_build_ids = set(recompute_build_ids) | set(
        FirmwareImage.objects.filter(pk__in=affected_pks).values_list(
            "build_id", flat=True
        )
    )
    build_statuses = dict(
        Build.objects.filter(pk__in=affected_build_ids).values_list("pk", "status")
    )
    for build_id in affected_build_ids:
        try:
            new_status = _compute_build_status(
                FirmwareImage, build_id, build_statuses.get(build_id)
            )
            if new_status:
                Build.objects.filter(pk=build_id).update(status=new_status)
        except Exception:
            logger.exception(
                "Failed to update extraction status for build %s", build_id
            )
    if affected_pks:
        post_migrate.connect(
            functools.partial(
                _send_multi_board_notifications, affected_pks=affected_pks
            ),
            dispatch_uid=_DISPATCH_UID,
            weak=False,
        )


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
