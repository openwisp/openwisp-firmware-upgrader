Settings
========

.. include:: /partials/settings-note.rst

``OPENWISP_FIRMWARE_UPGRADER_RETRY_OPTIONS``
--------------------------------------------

============ =========
**type**:    ``dict``
**default**: see below
============ =========

.. code-block:: python

    # default value of OPENWISP_FIRMWARE_UPGRADER_RETRY_OPTIONS:

    dict(
        max_retries=4,
        retry_backoff=60,
        retry_backoff_max=600,
        retry_jitter=True,
    )

Retry settings for recoverable failures during firmware upgrades.

By default if an upgrade operation fails before the firmware is flashed
(e.g.: because of a network issue during the upload of the image), the
upgrade operation will be retried 4 more times with an exponential random
backoff and a maximum delay of 10 minutes.

For more information regarding these settings, consult the `celery
documentation regarding automatic retries for known errors
<https://docs.celeryproject.org/en/stable/userguide/tasks.html#automatic-retry-for-known-exceptions>`_.

``OPENWISP_FIRMWARE_UPGRADER_TASK_TIMEOUT``
-------------------------------------------

============ ========
**type**:    ``int``
**default**: ``1500``
============ ========

Timeout for the background tasks which perform firmware upgrades and
firmware metadata extraction.

If for some unexpected reason an upgrade or metadata extraction remains
stuck for more than 25 minutes, the operation will be flagged as failed
and the task will be killed.

This should not happen, but a global task time out is a best practice when
using background tasks because it prevents the situation in which an
unexpected bug causes a specific task to hang, which will quickly fill all
the available slots in a background queue and prevent other tasks from
being executed, which will end up affecting negatively the rest of the
application.

``OPENWISP_FIRMWARE_UPGRADER_MAX_FILE_SIZE``
--------------------------------------------

============ ============================
**type**:    ``int``
**default**: ``30 * 1024 * 1024`` (30 MB)
============ ============================

This setting can be used to set the maximum size limit for firmware
images, e.g.:

.. code-block:: python

    OPENWISP_FIRMWARE_UPGRADER_MAX_FILE_SIZE = 40 * 1024 * 1024  # 40MB

**Notes**:

- Value must be specified in bytes. ``None`` means unlimited.

``OPENWISP_FIRMWARE_UPGRADER_MAX_KERNEL_BYTES``
-----------------------------------------------

============ ==============================
**type**:    ``int``
**default**: ``256 * 1024 * 1024`` (256 MB)
============ ==============================

Maximum number of bytes read from a firmware image during metadata
extraction, e.g.:

.. code-block:: python

    OPENWISP_FIRMWARE_UPGRADER_MAX_KERNEL_BYTES = 512 * 1024 * 1024  # 512MB

``OPENWISP_FIRMWARE_UPGRADER_MAX_DECOMPRESSED_BYTES``
-----------------------------------------------------

============ ==============================
**type**:    ``int``
**default**: ``512 * 1024 * 1024`` (512 MB)
============ ==============================

Maximum total bytes decompressed across the whole metadata extraction of
an image. This bounds total memory usage even when decompression happens
in multiple nested or repeated steps, e.g.:

.. code-block:: python

    OPENWISP_FIRMWARE_UPGRADER_MAX_DECOMPRESSED_BYTES = 768 * 1024 * 1024  # 768MB

``OPENWISP_FIRMWARE_UPGRADER_MAX_DECOMPRESSED_RATIO``
-----------------------------------------------------

============ =======
**type**:    ``int``
**default**: ``100``
============ =======

Maximum allowed ratio of decompressed size to compressed input size during
metadata extraction. This limit prevents malformed compressed images from
consuming all available memory, e.g.:

.. code-block:: python

    OPENWISP_FIRMWARE_UPGRADER_MAX_DECOMPRESSED_RATIO = 150

**Notes**:

- ``OPENWISP_FIRMWARE_UPGRADER_MAX_KERNEL_BYTES`` and
  ``OPENWISP_FIRMWARE_UPGRADER_MAX_DECOMPRESSED_BYTES`` are per-task
  memory ceilings, not global ones. Each is tracked cumulatively forr the
  whole task, not reset per decompression attempt. Multiple metadata
  extraction tasks can run concurently within the same Celery worker. Size
  the worker concurrency and the container memory limit so that
  ``concurrency * (MAX_KERNEL_BYTES + MAX_DECOMPRESSED_BYTES)`` fits
  within the available memory.

``OPENWISP_FIRMWARE_UPGRADER_MAX_TRAILER_PROBES``
-------------------------------------------------

============ =======
**type**:    ``int``
**default**: ``64``
============ =======

Maximum number of candidate fwtool metadata trailers scanned when
extracting firmware metadata. This limit prevents an image with many false
trailer signatures from causing excessive CPU work, e.g.:

.. code-block:: python

    OPENWISP_FIRMWARE_UPGRADER_MAX_TRAILER_PROBES = 32

``OPENWISP_FIRMWARE_UPGRADER_MAX_TRAILER_CRC_BYTES``
----------------------------------------------------

============ =============================
**type**:    ``int``
**default**: ``1024 * 1024 * 1024`` (1 GB)
============ =============================

Maximum total bytes checksummed across all trailer candidates during
metadata extraction. This bounds the total CRC32 work even when several
candidates are scanned, each covering a large portion of the file, e.g.:

.. code-block:: python

    OPENWISP_FIRMWARE_UPGRADER_MAX_TRAILER_CRC_BYTES = 256 * 1024 * 1024  # 256MB

**Notes**:

- The actual default is computed as 4x
  ``OPENWISP_FIRMWARE_UPGRADER_MAX_KERNEL_BYTES`` at settings-load time (1
  GB with the default 256 MB ``MAX_KERNEL_BYTES``), so it changes if you
  override that setting.

``OPENWISP_FIRMWARE_UPGRADER_MAX_DEEP_SCAN_PROBES``
---------------------------------------------------

============ =======
**type**:    ``int``
**default**: ``64``
============ =======

Maximum number of DTB (Device Tree Blob) candidates scanned when falling
back to DTB-based metadata extraction. This limit prevents an image with
many false DTB signatures from causing excessive CPU work, e.g.:

.. code-block:: python

    OPENWISP_FIRMWARE_UPGRADER_MAX_DEEP_SCAN_PROBES = 32

``OPENWISP_FIRMWARE_UPGRADER_QUEUE_UNCONFIRMED_CHUNK_SIZE``
-----------------------------------------------------------

============ =======
**type**:    ``int``
**default**: ``100``
============ =======

Number of firmware images dispatched per Celery task when
``queue_unconfirmed_extractions`` re-queues images stuck in the
``unconfirmed`` extraction status. This avoids flooding the broker with
one task per image on installs with a larger backlog, e.g.:

.. code-block:: python

    OPENWISP_FIRMWARE_UPGRADER_QUEUE_UNCONFIRMED_CHUNK_SIZE = 50

.. _openwisp_firmware_upgrader_queue_unconfirmed_on_worker_ready:

``OPENWISP_FIRMWARE_UPGRADER_QUEUE_UNCONFIRMED_ON_WORKER_READY``
----------------------------------------------------------------

============ ========
**type**:    ``bool``
**default**: ``True``
============ ========

Whether ``queue_unconfirmed_extractions`` is automatically triggered every
time a Celery worker starts up, so firmware images left ``unconfirmed``
(e.g. after an upgrade) are queued for extraction without requiring manual
intervention e.g.:

.. code-block:: python

    OPENWISP_FIRMWARE_UPGRADER_QUEUE_UNCONFIRMED_ON_WORKER_READY = False

**Notes**:

- See :doc:`recovering-from-extraction-failures` for more information.

.. _openwisp_firmware_upgrader_extraction_claim_timeout:

``OPENWISP_FIRMWARE_UPGRADER_EXTRACTION_CLAIM_TIMEOUT``
-------------------------------------------------------

============ =====================
**type**:    ``int``
**default**: ``3000`` (50 minutes)
============ =====================

Maximum number of seconds a firmware image can stay in ``in_progress``
extraction status before ``reclaim_stale_extractions`` considers it
abandoned (e.g. due to a worker crash) and marks it as failed, e.g.:

.. code-block:: python

    OPENWISP_FIRMWARE_UPGRADER_EXTRACTION_CLAIM_TIMEOUT = 1800  # 30 minutes

**Notes**:

- The actual default is computed as 2x
  ``OPENWISP_FIRMWARE_UPGRADER_TASK_TIMEOUT`` at settings-load time (3000
  seconds with the default 1500 second ``TASK_TIMEOUT``), so it changes if
  you override that setting.
- See :doc:`recovering-from-extraction-failures` for how this setting is
  used together with ``reclaim_stale_extractions`` and
  ``queue_unconfirmed_extractions``.

.. _openwisp_firmware_upgrader_api:

``OPENWISP_FIRMWARE_UPGRADER_API``
----------------------------------

============ ========
**type**:    ``bool``
**default**: ``True``
============ ========

Indicates whether the API for Firmware Upgrader is enabled or not.

``OPENWISP_FIRMWARE_UPGRADER_OPENWRT_SETTINGS``
-----------------------------------------------

============ ========
**type**:    ``dict``
**default**: ``{}``
============ ========

Allows changing the default OpenWrt upgrader settings, e.g.:

.. code-block:: python

    OPENWISP_FIRMWARE_UPGRADER_OPENWRT_SETTINGS = {
        "reconnect_delay": 180,
        "reconnect_retry_delay": 20,
        "reconnect_max_retries": 35,
        "upgrade_timeout": 90,
    }

- ``reconnect_delay``: amount of seconds to wait before trying to connect
  again to the device after the upgrade command has been launched; the
  re-connection step is necessary to verify the upgrade has completed
  successfully; defaults to ``120`` seconds
- ``reconnect_retry_delay``: amount of seconds to wait after a
  re-connection attempt has failed; defaults to ``20`` seconds
- ``reconnect_max_retries``: maximum re-connection attempts defaults to
  ``15`` attempts
- ``upgrade_timeout``: amount of seconds before the shell session is
  closed after the upgrade command is launched on the device, useful in
  case the upgrade command hangs (it happens on older OpenWrt versions);
  defaults to ``90`` seconds

``OPENWISP_FIRMWARE_API_BASEURL``
---------------------------------

============ =============================
**type**:    ``dict``
**default**: ``/`` (points to same server)
============ =============================

If you have a separate instance of OpenWISP Firmware Upgrader API on a
different domain, you can use this option to change the base of the image
download URL, this will enable you to point to your API server's domain,
e.g.: ``https://api.myservice.com``.

.. _openwisp_firmware_upgraders_map:

``OPENWISP_FIRMWARE_UPGRADERS_MAP``
-----------------------------------

============ ================================================================================================================================
**type**:    ``dict``
**default**: .. code-block:: python

                 {
                     "openwisp_controller.connection.connectors.openwrt.ssh.OpenWrt": "openwisp_firmware_upgrader.upgraders.openwrt.OpenWrt",
                 }
============ ================================================================================================================================

A dictionary that maps update strategies to upgraders.

If you want to use a custom update strategy you will need to use this
setting to provide an entry with the class path of your update strategy as
the key.

If you need to use a :doc:`custom upgrader class
<custom-firmware-upgrader>` you will need to use this setting to provide
an entry with the class path of your upgrader as the value.

``OPENWISP_FIRMWARE_PRIVATE_STORAGE_INSTANCE``
----------------------------------------------

============ ==================================================================================
**type**:    ``str``
**default**: ``openwisp_firmware_upgrader.private_storage.storage.file_system_private_storage``
============ ==================================================================================

Dotted path to an instance of any one of the storage classes in
`private_storage
<https://github.com/edoburu/django-private-storage#django-private-storage>`_.
This instance is used to store firmware image files.

By default, an instance of
``private_storage.storage.files.PrivateFileSystemStorage`` is used.

.. _openwisp_custom_openwrt_images:

``OPENWISP_CUSTOM_OPENWRT_IMAGES``
----------------------------------

.. warning::

    This setting is deprecated and retained only for backward
    compatibility with the legacy static hardware map. It will be removed
    in a future release. Firmware metadata (board, target, compatible
    devices) is now detected automatically at upload time — see
    :doc:`automatic-device-firmware-detection`.

============ =========
**type**:    ``tuple``
**default**: ``None``
============ =========

This setting was historically used to extend the static list of firmware
image types recognized by *OpenWISP Firmware Upgrader* before automatic
metadata extraction was introduced.

.. code-block:: python

    OPENWISP_CUSTOM_OPENWRT_IMAGES = (
        (
            # Firmware image file name.
            "customimage-squashfs-sysupgrade.bin",
            {
                # Human readable name of the model which is displayed on
                # the UI
                "label": "Custom WAP-1200",
                # Tuple of board names with which the different versions of
                # the hardware are identified on OpenWrt
                "boards": ("CWAP1200",),
            },
        ),
    )
