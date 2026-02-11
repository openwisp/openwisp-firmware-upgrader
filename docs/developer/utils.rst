Code Utilities
==============

.. include:: ../partials/developer-docs.rst

.. contents:: **Table of Contents**:
    :depth: 2
    :local:

Signals
-------

.. include:: /partials/signals-note.rst

``firmware_upgrader_log_updated``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Path**:
``openwisp_firmware_upgrader.signals.firmware_upgrader_log_updated``

**Arguments**:

- ``sender``: the model class that sent the signal (``UpgradeOperation``)
- ``instance``: instance of ``UpgradeOperation`` which got its log updated
- ``line``: the new log line that was appended
- ``**kwargs``: additional keyword arguments

This signal is emitted when the log content of an upgrade operation is
updated. You can use this signal to perform custom actions when log
updates occur, such as sending notifications, updating external systems,
or logging to custom destinations.
