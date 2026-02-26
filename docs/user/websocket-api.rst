WebSocket Reference
===================

.. contents:: **Table of contents**:
    :depth: 2
    :local:

Overview
--------

The WebSocket API provides real-time updates for firmware upgrade
operations.

All endpoints:

- Use JSON messages.
- Support requesting the current state of the connection scope.
- May push real-time updates after the connection is established.

Authentication and Authorization
--------------------------------

All WebSocket endpoints require an authenticated user.

A connection is accepted only if the user is authorized to access the
requested resource. The connection is closed immediately if authorization
fails.

A user is authorized if:

- The user is a superuser, OR
- The user:

  - Is marked as staff,
  - Has either ``view`` or ``change`` permission on the relevant object,
  - Is an organization admin (manager) for the object's organization.

Connection Endpoints
--------------------

1. Upgrade Operation
~~~~~~~~~~~~~~~~~~~~

Connection URL:

::

    wss://<host>/ws/firmware-upgrader/upgrade-operation/<operation_id>/

Scope
+++++

A single upgrade operation.

Client Message
++++++++++++++

To request the current state of the operation:

.. code-block:: javascript

    {
        "type": "request_current_state",    // Required. Requests current operation state.
        "operation_id": "<uuid>"            // Must match the <operation_id> in the URL.
    }

.. warning::

    Any other message type is ignored.

When the client sends ``request_current_state``, the server responds with
exactly one message:

.. code-block:: javascript

    {
        "type": "operation_update",         // Message type identifier
        "operation": {
            "id": "<uuid>",                 // Operation identifier
            "device": "<uuid>",             // Device identifier
            "image": "<uuid>",              // Firmware image identifier
            "status": "<string>",           // Current operation status
            "log": "<string>",              // Operation log output
            "progress": <integer>,          // Progress percentage (0–100)
            "modified": "<datetime>",       // Last modification timestamp (ISO 8601)
            "created": "<datetime>"         // Creation timestamp (ISO 8601)
        }
    }

Real-time Updates
+++++++++++++++++

After the connection is established, the server pushes
``operation_update`` messages whenever the operation state changes.

The message structure is identical to the response returned for
``request_current_state``.

2. Batch Upgrade Operation
~~~~~~~~~~~~~~~~~~~~~~~~~~

Connection URL:

::

    wss://<host>/ws/firmware-upgrader/batch-upgrade-operation/<batch_id>/

Scope
+++++

A batch upgrade containing multiple operations.

Client Message
++++++++++++++

To request the current state of the batch:

.. code-block:: javascript

    {
        "type": "request_current_state",    // Required. Requests current batch state.
        "batch_id": "<uuid>"                // Must match the <batch_id> in the URL.
    }

.. warning::

    Any other message type is ignored.

When the client sends ``request_current_state``, the server responds with
exactly one message:

.. code-block:: javascript

    {
        "type": "batch_state",              // Message type identifier
        "batch_status": {
            "status": "<string>",           // Overall batch status
            "completed": <integer>,         // Number of completed operations
            "total": <integer>              // Total operations in the batch
        },
        "operations": [
            {
                "id": "<uuid>",             // Operation identifier
                "device": "<uuid>",         // Device identifier
                "image": "<uuid>",          // Firmware image identifier
                "status": "<string>",       // Operation status
                "log": "<string>",          // Operation log output
                "progress": <integer>,      // Progress percentage (0–100)
                "modified": "<datetime>",   // Last modification timestamp
                "created": "<datetime>"     // Creation timestamp
            }
        ]
    }

Real-time Updates
+++++++++++++++++

The endpoint may push:

``operation_progress``

.. code-block:: javascript

    {
        "type": "operation_progress",       // Message type identifier
        "operation_id": "<uuid>",           // Operation identifier
        "status": "<string>",               // Operation status
        "progress": <integer>,              // Progress percentage (0–100)
        "modified": "<datetime>",           // Last modification timestamp
        "device_id": "<uuid>",              // Device identifier
        "device_name": "<string>",          // Device display name
        "image_name": "<string>"            // Firmware image display name
    }

``batch_status``

.. code-block:: javascript

    {
        "type": "batch_status",             // Message type identifier
        "status": "<string>",               // Overall batch status
        "completed": <integer>,             // Number of completed operations
        "total": <integer>                  // Total operations in the batch
    }

3. Device Upgrade
~~~~~~~~~~~~~~~~~

Connection URL:

::

    wss://<host>/ws/firmware-upgrader/device/<device_id>/

Scope
+++++

Recent and ongoing upgrade operations for a device.

Client Message
++++++++++++++

To request the current state for the device:

.. code-block:: javascript

    {
        "type": "request_current_state",    // Required. Requests device upgrade state.
        "device_id": "<uuid>"               // Must match the <device_id> in the URL.
    }

.. warning::

    Any other message type is ignored.

When ``request_current_state`` is sent, the server sends up to five
separate messages (one per operation).

Each message uses the following envelope:

.. code-block:: javascript

    {
        "model": "UpgradeOperation",        // Model identifier
        "data": {
            "type": "operation_update",     // Message type identifier
            "operation": {
                "id": "<uuid>",             // Operation identifier
                "device": "<uuid>",         // Device identifier
                "image": "<uuid>",          // Firmware image identifier
                "status": "<string>",       // Operation status
                "log": "<string>",          // Operation log output
                "progress": <integer>,      // Progress percentage (0–100)
                "modified": "<datetime>"    // Last modification timestamp
            }
        }
    }

Real-time Updates
+++++++++++++++++

After the connection is established, the server forwards
``operation_update`` events for upgrade operations related to the device.

Real-time messages use the same envelope structure as described above and
are emitted individually as operation state changes occur.
