from django.db import migrations
from django.db.models.signals import post_migrate

from openwisp_firmware_upgrader.tasks import queue_unconfirmed_extractions


def _queue_legacy_extractions(app_config, **kwargs):
    if app_config.name != "openwisp_firmware_upgrader":
        return
    post_migrate.disconnect(_queue_legacy_extractions)
    queue_unconfirmed_extractions.delay()


# Queueing must run afterr the whole `migrate` command completes, because the
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
