import logging

from django.db import migrations
from django.db.models.signals import post_migrate

from openwisp_firmware_upgrader.tasks import queue_unconfirmed_extractions

logger = logging.getLogger(__name__)


def _queue_legacy_extractions(app_config, **kwargs):
    if app_config.name != "openwisp2.sample_firmware_upgrader":
        return
    post_migrate.disconnect(_queue_legacy_extractions)
    try:
        queue_unconfirmed_extractions.delay()
    except Exception:
        logger.exception(
            "Failed to queue legacy unconfirmed firmware image extractions"
        )


# Queueing must run after the whole `migrate` command completes, because the
# Celery worker reads committed rows, `RunPython` therefore only registers a
# one-shot `post_migrate` receiver instead of enqueueing directly
def register_legacy_extraction_queueing(apps, schema_editor):
    post_migrate.connect(_queue_legacy_extractions)


class Migration(migrations.Migration):
    dependencies = [
        ("sample_firmware_upgrader", "0007_alter_firmwareimage_compatible_and_more"),
    ]
    operations = [
        migrations.RunPython(
            register_legacy_extraction_queueing,
            reverse_code=migrations.RunPython.noop,
        )
    ]
