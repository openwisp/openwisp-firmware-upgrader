from django.conf import settings
from django.core import checks

from . import settings as app_settings


@checks.register()
def check_extraction_claim_timeout(app_configs, **kwargs):
    errors = []
    if app_settings.EXTRACTION_CLAIM_TIMEOUT < app_settings.TASK_TIMEOUT:
        errors.append(
            checks.Warning(
                msg=(
                    "OPENWISP_FIRMWARE_UPGRADER_EXTRACTION_CLAIM_TIMEOUT is "
                    "lower than OPENWISP_FIRMWARE_UPGRADER_TASK_TIMEOUT."
                ),
                hint=(
                    "The stale extraction reaper may mark a still-running "
                    "extraction as failed before it has a chance to "
                    "complete. Set EXTRACTION_CLAIM_TIMEOUT to at least "
                    "TASK_TIMEOUT."
                ),
                obj="OPENWISP_FIRMWARE_UPGRADER_EXTRACTION_CLAIM_TIMEOUT",
            )
        )
    return errors


@checks.register()
def check_reclaim_stale_extractions_scheduled(app_configs, **kwargs):
    errors = []
    schedule = getattr(settings, "CELERY_BEAT_SCHEDULE", {})
    scheduled_tasks = {entry.get("task") for entry in schedule.values()}
    if (
        "openwisp_firmware_upgrader.tasks.reclaim_stale_extractions"
        not in scheduled_tasks
    ):
        errors.append(
            checks.Warning(
                msg="'reclaim_stale_extractions' task is not scheduled",
                hint=(
                    "Firmware images stuck 'in_progress' extraction "
                    "status will not be recovered automatically. See the "
                    "'Recovering from extraction failures' documentation."
                ),
                obj="CELERY_BEAT_SCHEDULE",
            )
        )
    return errors
