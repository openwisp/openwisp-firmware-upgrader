import logging

from django.core.cache import cache
from django.db import migrations
from django.db.models.signals import post_migrate

from openwisp_firmware_upgrader import settings as app_settings
from openwisp_firmware_upgrader.tasks import queue_unconfirmed_extractions

logger = logging.getLogger(__name__)


def _queue_legacy_extractions(app_config, **kwargs):
    if app_config.name != "openwisp_firmware_upgrader":
        return
    post_migrate.disconnect(_queue_legacy_extractions)
    try:
        # shares the worker_ready lock key so a deploy that both migrates and
        # restarts workers in the same rollout doesn't queue the backlog twice
        lock_acquired = cache.add(
            "firmware_upgrader.queue_unconfirmed_lock",
            True,
            timeout=app_settings.QUEUE_UNCONFIRMED_LOCK_TIMEOUT,
        )
        if not lock_acquired:
            return
        queue_unconfirmed_extractions.delay()
    except Exception:
        logger.exception(
            "Failed to queue legacy unconfirmed firmware image extractions. "
            "If QUEUE_UNCONFIRMED_ON_WORKER_READY is enabled (the default), "
            "this will be retried automatically on the next Celery worker "
            "restart. If not, run the 'queue_unconfirmed_extractions' "
            "Celery task manually to retry."
        )
        try:
            cache.delete("firmware_upgrader.queue_unconfirmed_lock")
        except Exception:
            logger.warning("Failed to release queue_unconfirmed lock", exc_info=True)


# Queueing must run after the whole `migrate` command completes, because the
# Celery worker reads committed rows, `RunPython` therefore only registers a
# one-shot `post_migrate` receiver instead of enqueueing directly
def register_legacy_extraction_queueing(apps, schema_editor):
    post_migrate.connect(_queue_legacy_extractions)


class Migration(migrations.Migration):
    dependencies = [
        ("firmware_upgrader", "0018_build_status_firmwareimage_board_and_more"),
    ]
    operations = [
        migrations.RunPython(
            register_legacy_extraction_queueing,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
