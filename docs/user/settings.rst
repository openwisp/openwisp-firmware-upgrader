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

============ =======
**type**:    ``int``
**default**: ``600``
============ =======

Timeout for the background tasks which perform firmware upgrades.

If for some unexpected reason an upgrade remains stuck for more than 10
minutes, the upgrade operation will be flagged as failed and the task will
be killed.

This should not happen, but a global task time out is a best practice when
using background tasks because it prevents the situation in which an
unexpected bug causes a specific task to hang, which will quickly fill all
the available slots in a background queue and prevent other tasks from
being executed, which will end up affecting negatively the rest of the
application.

.. _openwisp_custom_openwrt_images:

``OPENWISP_CUSTOM_OPENWRT_IMAGES``
----------------------------------

============ =========
**type**:    ``tuple``
**default**: ``None``
============ =========

This setting can be used to extend the list of firmware image types
included in *OpenWISP Firmware Upgrader*. This setting is suited to add
support for custom OpenWrt images.

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

Kindly read :doc:`automatic-device-firmware-detection` section of this
documentation to know how *OpenWISP Firmware Upgrader* uses this setting
in upgrades.

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
