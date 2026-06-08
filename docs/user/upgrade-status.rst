Upgrade Status
==============

OpenWISP Firmware Upgrader tracks the progress of firmware upgrade
operations through different status values. Understanding these statuses
is helpful for monitoring upgrade operations and troubleshooting issues.

.. contents:: **Table of contents**:
    :depth: 2
    :local:

Upgrade Operation Status Reference
----------------------------------

In Progress
~~~~~~~~~~~

**Status**: ``in-progress``

**Description**: The upgrade operation is currently running. This includes
all phases of the upgrade process: device connection, firmware validation,
file upload, and firmware flashing.

**What happens during this status:**

- Device identity verification
- Firmware image validation
- Some non-critical services may be stopped to free up memory, if needed
- Image upload to the device
- Firmware flashing process

**User Actions**: Users can cancel upgrade operations that are in
progress, but only before the firmware flashing phase begins (typically
when progress is below 65%).

Pending
~~~~~~~

**Status**: ``pending``

**Description**: The device was unreachable when the upgrade was last
attempted. The operation keeps a future ``next_retry_at`` and a Celery
Beat task picks it up later. This is the status that persistent mass
upgrades use while a device is offline.

**What happens during this status:**

- ``retry_count`` is incremented and ``next_retry_at`` is scheduled with
  an exponential backoff (10m → 20m → 40m → ..., capped at 12 hours, with
  ±25% jitter)
- A periodic Beat task scans for pending operations whose
  ``next_retry_at`` has elapsed and re-dispatches them
- A device deactivated while pending is set to ``failed`` and not retried

**User Actions**: Pending operations can be cancelled the same way as
in-progress ones, both from the admin and the REST API. Starting another
upgrade on the same device is blocked while one is pending, so the device
cannot be flashed twice. ``pending`` is treated as an active, non-terminal
state by the deletion guard: a pending operation cannot be deleted
directly and must be cancelled or left to reach a terminal state first
(see :ref:`Deleting Upgrade Operations <deleting_upgrade_operations>`).

Success
~~~~~~~

**Status**: ``success``

**Description**: The firmware upgrade completed successfully. The device
has been upgraded to the new firmware version and is functioning properly.

**What this means:**

- The firmware was successfully flashed to the device
- The device rebooted with the new firmware
- Connectivity was restored after the upgrade
- All verification checks passed

**Next Steps**: No action required. The upgrade is complete and the device
is running the new firmware.

Failed
~~~~~~

**Status**: ``failed``

**Description**: The upgrade operation completed, but the system could not
reach the device again after the upgrade.

**Common causes:**

- Hardware failures
- Unexpected system errors
- The network became unreachable after flashing the new firmware

**Recommended Actions**:

- Check network connectivity
- Physical inspection and/or serial console debugging

Aborted
~~~~~~~

**Status**: ``aborted``

**Description**: The upgrade operation was stopped due to prerequisites
not being met. The system determined it was unsafe or impossible to
proceed with the upgrade.

**Common causes:**

- Device UUID mismatch (wrong device targeted)
- Insufficient memory on the device
- Invalid or corrupted firmware image

**What happens when aborted:**

- The upgrade stops immediately
- If services were stopped to free up memory, they are automatically
  restarted
- No firmware changes are made to the device
- Device remains in its original state

**Recommended Actions**:

- Verify the correct device is selected
- Check firmware image compatibility
- Ensure device has sufficient memory

Cancelled
~~~~~~~~~

**Status**: ``cancelled``

**Description**: The upgrade operation was manually stopped by the user
before completion. This is a deliberate action taken through the admin
interface or REST API.

Users can cancel upgrades through the admin interface using the "Cancel"
button that appears next to in-progress operations.

**When cancellation is possible:**

- During the early stages of upgrade (typically before 65% progress)
- Before the new firmware image is written to the flash memory of the
  network device
- While the operation status is still "in-progress"

**What happens when the upgrade operation is cancelled:**

- The upgrade process stops immediately
- If services were stopped during the upgrade, they are automatically
  restarted
- No firmware changes are made to the device
- Device remains in its original state

Status Flow
-----------

A firmware upgrade operation always starts in the ``in-progress`` state.
From there, it can transition into one of several terminal states
depending on how the operation concludes.

Successful Flow
~~~~~~~~~~~~~~~

In the normal case, the upgrade proceeds without interruption:

1. ``in-progress``: the upgrade is executed;
2. ``success``: the device reboots and becomes reachable again.

This indicates a fully completed and verified upgrade.

Interrupted or Unsuccessful Flows
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

An upgrade may also end prematurely or unsuccessfully:

- ``aborted``: the system detects that one or more safety preconditions
  are not met *before* flashing begins and stops the operation without
  making any changes to the device;
- ``cancelled``: the user manually stops the upgrade while it is still
  safe to do so, firmware flash is prevented;
- ``failed``: the firmware flashing process completes, but the device does
  not become reachable afterward, it usually indicates a post-flash
  failure.

Terminal States
~~~~~~~~~~~~~~~

The following statuses are terminal and will not transition further:

- ``success``
- ``failed``
- ``aborted``
- ``cancelled``

Once a terminal state is reached, a new upgrade operation must be
initiated to retry or recover.

Monitoring Upgrades
-------------------

**Real-time Progress**: The admin interface provides real-time updates of
upgrade operations, including progress percentages and detailed logs. See
:doc:`websocket-api` for details on the WebSocket API used to deliver
these updates.

**Upgrade Logs**: Each status change is logged with detailed information
about what occurred during the upgrade process.

**Batch Operations**: When performing mass upgrades, you can monitor the
status of individual device upgrades within the batch operation.

.. _deleting_upgrade_operations:

Deleting Upgrade Operations
---------------------------

Upgrade operations and batch upgrade operations can be deleted from the
admin interface only after they leave the ``in-progress`` state. The
``pending`` state is guarded the same way: a pending operation is still
active (it is waiting to be retried), so it cannot be deleted until it is
cancelled or reaches a terminal state.

Deleting an operation while it is still running is intentionally blocked
because the upgrade may be uploading or flashing a firmware image,
restarting services, or waiting for the device to reconnect. Removing the
operation at that point would make the outcome harder to track and would
introduce risky edge cases around partially completed upgrades.

If an upgrade is still in progress and the firmware image has not started
flashing yet, cancel the operation instead. If cancellation is no longer
available, wait until the operation completes and reaches one of the
terminal states before deleting it.

The same rule applies to mass upgrades: a batch upgrade operation cannot
be deleted while it is still ``in-progress``. Once the batch reaches a
terminal state such as ``success``, ``failed``, or ``cancelled``, it can
be deleted from the admin interface if the user has the required delete
permission.
