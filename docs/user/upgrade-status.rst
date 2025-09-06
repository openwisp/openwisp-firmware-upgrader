Upgrade Status Reference
========================

.. contents:: **Table of contents**:
    :depth: 2
    :local:

Overview
--------

OpenWISP Firmware Upgrader tracks the progress of firmware upgrade
operations through different status values. Understanding these statuses
is essential for monitoring upgrade operations and troubleshooting issues.

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
when progress is below 60%).

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

**Description**: The upgrade operation was stopped due to pre-requisites
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

- During the early stages of upgrade (typically before 60% progress)
- Before the new firmware image is written to the flash memory of the
  network device
- While the operation status is still "in-progress"

**What happens when the upgrade operation cancels:**

- The upgrade process stops immediately
- If services were stopped during the upgrade, they are automatically
  restarted
- No firmware changes are made to the device
- Device remains in its original state

Status Flow
-----------

The typical flow of upgrade statuses follows this pattern:

.. code-block:: none

    in-progress → success
               ↓
               failed/aborted/cancelled

**Typical successful upgrade:**

1. ``in-progress``
2. ``success``

**Typical problematic upgrade:**

1. ``in-progress`` 3. ``failed``: an unexpected error occurs during
upgrade 2. **OR** ``aborted``: the system detects pre-condition failure
and stops safely 4. **OR** ``cancelled``: the user manually stops the
upgrade

Monitoring Upgrades
-------------------

**Real-time Progress**: The admin interface provides real-time updates of
upgrade operations, including progress percentages and detailed logs.

**Upgrade Logs**: Each status change is logged with detailed information
about what occurred during the upgrade process.

**Batch Operations**: When performing mass upgrades, you can monitor the
status of individual device upgrades within the batch operation.
