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

Status Types
------------

The firmware upgrader uses five distinct status values to represent
different states of an upgrade operation:

In Progress
~~~~~~~~~~~

**Status**: ``in-progress``

**Description**: The upgrade operation is currently running. This includes
all phases of the upgrade process: device connection, firmware validation,
file upload, and firmware flashing.

**What happens during this status:**

- Device identity verification
- Firmware image validation
- Memory optimization (stopping non-critical services if needed)
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
- Device connectivity was restored after the upgrade
- All verification checks passed

**Next Steps**: No action required. The upgrade is complete and the device
is running the new firmware.

Failed
~~~~~~

**Status**: ``failed``

**Description**: The upgrade operation encountered an unrecoverable error
and could not be completed. This typically indicates network issues,
device connectivity problems, or unexpected errors during the upgrade
process.

**Common causes:**

- Network connectivity lost during upgrade
- Device became unreachable after firmware flashing
- Unexpected system errors
- Hardware failures

**Recommended Actions**:

- Check device connectivity
- Review upgrade logs for specific error messages
- Verify network infrastructure
- Consider manual device recovery if needed

Aborted
~~~~~~~

**Status**: ``aborted``

**Description**: The upgrade operation was stopped due to pre-condition
checks or validation failures. The system determined it was unsafe or
impossible to proceed with the upgrade.

**Common causes:**

- Device UUID mismatch (wrong device targeted)
- Insufficient memory on the device
- Invalid or corrupted firmware image
- Device configuration incompatibility
- Pre-upgrade validation failures

**What happens when aborted:**

- The upgrade stops immediately
- If services were stopped to free memory, they are automatically
  restarted
- No firmware changes are made to the device
- Device remains in its original state

**Recommended Actions**:

- Verify the correct device is selected
- Check firmware image compatibility
- Ensure device has sufficient memory
- Review device configuration

Cancelled
~~~~~~~~~

**Status**: ``cancelled``

**Description**: The upgrade operation was manually stopped by a user
before completion. This is a deliberate action taken through the admin
interface or API.

**When cancellation is possible:**

- During the early stages of upgrade (typically before 60% progress)
- Before firmware flashing begins
- While the operation status is still "in-progress"

**What happens when cancelled:**

- The upgrade process stops immediately
- If services were stopped during the upgrade, they are automatically
  restarted
- No firmware changes are made to the device
- Device remains in its original state

**User Interface**: Users can cancel upgrades through the admin interface
using the "Cancel" button that appears next to in-progress operations.

Status Flow
-----------

The typical flow of upgrade statuses follows this pattern:

.. code-block:: none

    in-progress → success
                 ↓
              failed/aborted/cancelled

**Normal successful upgrade:**

1. ``in-progress`` - Upgrade begins and progresses through all phases
2. ``success`` - Upgrade completes successfully

**Upgrade with issues:**

1. ``in-progress`` - Upgrade begins
2. ``aborted`` - System detects pre-condition failure and stops safely
3. **OR** ``failed`` - Unexpected error occurs during upgrade
4. **OR** ``cancelled`` - User manually stops the upgrade

Monitoring Upgrades
-------------------

**Real-time Progress**: The admin interface provides real-time updates of
upgrade operations, including progress percentages and detailed logs.

**Upgrade Logs**: Each status change is logged with detailed information
about what occurred during the upgrade process.

**Batch Operations**: When performing mass upgrades, you can monitor the
status of individual device upgrades within the batch operation.

Troubleshooting
---------------

**Aborted Upgrades**: - Check the upgrade logs for specific validation
errors - Verify device compatibility with the firmware image - Ensure
device has sufficient memory and storage

**Failed Upgrades**: - Check network connectivity to the device - Review
device logs if accessible - Verify device hardware is functioning properly

**Stuck in Progress**: - Operations may appear stuck if network
connectivity is intermittent - The system includes timeout mechanisms to
handle unresponsive devices - Check device accessibility and network
stability

**Cancellation Issues**: - Cancellation is only possible during early
stages of the upgrade - Once firmware flashing begins, the operation
cannot be safely cancelled - The interface will indicate when cancellation
is no longer possible
