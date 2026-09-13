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

To avoid woker process re-queuing the entire backlog on the same restart,
this is guarded by a short-lived cache lock (see
:ref:`OPENWISP_FIRMWARE_UPGRADER_QUEUE_UNCONFIRMED_LOCK_TIMEOUT
<openwisp_firmware_upgrader_queue_unconfirmed_lock_timeout>`). This only
works as intended if ``CACHES`` is configured with a backend shared across
worker processes (e.g. Redis or Memcached); with a per-process backend
such as Django's local-memory cache, each worker will still queue the
backlog independently.

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

Impact on Mass Upgrades
-----------------------

A build's mass upgrade can only be launched once every firmware image
belonging to it has left the ``unconfirmed``/``in_progress`` extraction
states and reached ``success``, ``incomplete``, or ``manually_confirmed``.
If even a single image in the build is still ``unconfirmed``,
``in_progress``, ``failed``, or ``invalid``, launching a mass upgrade for
that build is blocked entirely with a validation error, regardless of how
many other images in the same build are ready.

This means a stuck extraction on a single image (see above) can hold up
the mass upgrade of an entire build. Recovering the extraction promptly,
or manually confirming/correcting the offending image's metadata, is
required before the mass upgrade can proceed.
