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
