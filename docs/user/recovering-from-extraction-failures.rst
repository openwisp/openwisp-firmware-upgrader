Recovering From Extraction Failures
===================================

Metadata extraction runs in the background via Celery. If a worker
crashes, is killed due to an out-of-memory condition, or hits Celery's
hard time limit while extracting metadata, the ordinary exception handlers
are bypassed and the affected firmware image can be left stuck in an
``in_progress`` state indefinitely.

Similarly, in rare cases (e.g. a message broker outage), a background task
responsible for queueing extraction of previously ``unconfirmed`` images
may fail to be scheduled.

*OpenWISP Firmware Upgrader* provides two Celery tasks that recover from
these situations:

- ``openwisp_firmware_upgrader.tasks.reclaim_stale_extractions``: finds
  firmware images stuck in ``in_progress`` extraction status for longer
  than :ref:`OPENWISP_FIRMWARE_UPGRADER_EXTRACTION_CLAIM_TIMEOUT
  <openwisp_firmware_upgrader_extraction_claim_timeout>` seconds and marks
  them as failed, so they can be manually re-extracted or edited.
- ``openwisp_firmware_upgrader.tasks.queue_unconfirmed_extractions``:
  finds firmware images which are still ``unconfirmed`` and queues
  metadata extraction for them.

Additionally, ``queue_unconfirmed_extractions`` is automatically triggered
every time a Celery worker starts up (via Celery's ``worker_ready``
signal), so any firmware images left ``unconfirmed`` after an upgrade or a
worker restart are queued for extraction without requiring any manual
steps. Restarting a worker is itself enough to retry it on demand. This
can be disabled with
:ref:`OPENWISP_FIRMWARE_UPGRADER_QUEUE_UNCONFIRMED_ON_WORKER_READY
<openwisp_firmware_upgrader_queue_unconfirmed_on_worker_ready>`.

Both tasks are idempotent and safe to run at any time, including
concurrently with themselves. To ensure firmware images automatically
recover from the situations described above without requiring manual
intervention, it is recommended to schedule these tasks periodically using
Celery Beat, e.g.:

.. code-block:: python

    from datetime import timedelta

    CELERY_BEAT_SCHEDULE.update(
        {
            "queue_unconfirmed_extractions": {
                "task": "openwisp_firmware_upgrader.tasks.queue_unconfirmed_extractions",
                "schedule": timedelta(minutes=15),  # adjust to your deployment's needs
            },
            "reclaim_stale_extractions": {
                "task": "openwisp_firmware_upgrader.tasks.reclaim_stale_extractions",
                "schedule": timedelta(minutes=15),  # adjust to your deployment's needs
            },
        }
    )

Please refer to the `"Periodic Tasks" section of Celery's documentation
<https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html>`_ to
learn more.
