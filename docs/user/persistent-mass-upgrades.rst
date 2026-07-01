Persistent Mass Upgrades
========================

When a mass upgrade runs against a large fleet, some devices are usually
offline at that moment. Without persistence, each unreachable device ends
as ``failed`` once the immediate retries are exhausted, leaving the
operator to track down and re-launch every failed device by hand.

A *persistent* mass upgrade does not give up on offline devices. Instead
of marking them ``failed``, it parks them in the ``pending`` state with a
scheduled retry time and keeps retrying in the background until the device
comes back online or the operation is cancelled.

.. contents:: **Table of contents**:
    :depth: 2
    :local:

How it works
------------

An operation whose device is unreachable transitions to ``pending``
instead of ``failed``, with an incremented ``retry_count`` and an
exponential-backoff ``next_retry_at`` (10 minutes, doubling on each retry
up to a 12-hour cap, with ±25% jitter). A periodic Celery Beat task
re-dispatches pending operations once their retry time has elapsed, and
the batch stays ``in-progress`` until every device has either upgraded or
been cancelled.

.. image:: https://raw.githubusercontent.com/openwisp/openwisp-firmware-upgrader/docs/docs/images/1.4/persistent-upgrades/mass-upgrade.png
    :target: https://raw.githubusercontent.com/openwisp/openwisp-firmware-upgrader/docs/docs/images/1.4/persistent-upgrades/mass-upgrade.png

The mass-upgrade page above stays ``in progress`` while one device is
still ``pending``, reporting ``2 complete, 1 pending`` and keeping the
batch open until the offline device is retried successfully or cancelled.

See :doc:`upgrade-status` for the full operation state machine and the
meaning of the ``pending`` state.

Enabling from the admin
-----------------------

On the mass-upgrade confirmation page (reached from a build's *Upgrade*
action) the **persistent** checkbox is shown pre-checked. Leave it checked
to keep retrying offline devices, or uncheck it to fall back to the
behaviour where unreachable devices end as ``failed``.

.. image:: https://raw.githubusercontent.com/openwisp/openwisp-firmware-upgrader/docs/docs/images/1.4/persistent-upgrades/mass-upgrade-confirm.png
    :target: https://raw.githubusercontent.com/openwisp/openwisp-firmware-upgrader/docs/docs/images/1.4/persistent-upgrades/mass-upgrade-confirm.png

The flag is locked in once the mass upgrade leaves the ``idle`` state, so
it cannot be changed midway through a running batch.

Enabling via the REST API
~~~~~~~~~~~~~~~~~~~~~~~~~

The mass-upgrade endpoint accepts an ``is_persistent`` field that defaults
to ``true``; the single-device upgrade endpoint accepts the same field but
defaults to ``false``. See :doc:`rest-api` for the full request and
response reference.

Finding pending operations
--------------------------

Pending operations are listed in the upgrade-operation admin and can be
isolated with the ``status`` filter set to ``pending``. The list shows the
``persistent`` flag and the ``retry_count`` column, the latter being how
many times an operation has been retried so far.

.. image:: https://raw.githubusercontent.com/openwisp/openwisp-firmware-upgrader/docs/docs/images/1.4/persistent-upgrades/pending-operations-list.png
    :target: https://raw.githubusercontent.com/openwisp/openwisp-firmware-upgrader/docs/docs/images/1.4/persistent-upgrades/pending-operations-list.png

An operation's detail page adds ``next_retry_at`` (when the next attempt
is scheduled) and a log that records each attempt, ending with the
backoff-scheduled ``persistent retry`` line for the next run.

.. image:: https://raw.githubusercontent.com/openwisp/openwisp-firmware-upgrader/docs/docs/images/1.4/persistent-upgrades/pending-operation.png
    :target: https://raw.githubusercontent.com/openwisp/openwisp-firmware-upgrader/docs/docs/images/1.4/persistent-upgrades/pending-operation.png

Cancelling a pending operation
------------------------------

A pending operation is still active, so it can be cancelled the same way
as an in-progress one — from the admin cancel button or the REST cancel
endpoint. Cancelling stops the retry loop and moves the operation to
``cancelled``. A pending operation cannot be *deleted* until it reaches a
terminal state (see :ref:`deleting_upgrade_operations`).

Notifications
-------------

Two notifications keep operators informed about long-running persistent
upgrades:

- a **reminder** fires when a persistent batch still has pending children
  after the configured cadence has elapsed, and
- a **failure** notification fires when a persistent operation finally
  ends as ``failed`` (for example, the device was deactivated while
  pending).

Both are delivered to the organization's administrators (and superusers).

.. image:: https://raw.githubusercontent.com/openwisp/openwisp-firmware-upgrader/docs/docs/images/1.4/persistent-upgrades/notifications.png
    :target: https://raw.githubusercontent.com/openwisp/openwisp-firmware-upgrader/docs/docs/images/1.4/persistent-upgrades/notifications.png

The cadence and related settings are documented in :doc:`settings`.

Behaviour with and without openwisp-monitoring
----------------------------------------------

Persistent upgrades work with Celery Beat alone: the periodic scan retries
due pending operations on a fixed cadence. Installing
``openwisp-monitoring`` adds a faster wake-up path — a device returning to
a healthy state triggers its pending retries immediately, without waiting
for the next scan. When ``openwisp-monitoring`` is not installed, the Beat
scan remains the only retry trigger.

The periodic tasks (``check_pending_upgrades`` and
``send_pending_upgrade_reminders``) must be present in the deployment's
``CELERY_BEAT_SCHEDULE``; see :doc:`settings`.
