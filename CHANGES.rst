Changelog
=========

Version 1.0.1 [2022-06-10]
--------------------------

Bugfixes
--------

- Fixed `hardcoded storage backend of the "FirmwareImage.file" field
  <https://github.com/openwisp/openwisp-firmware-upgrader/issues/195>`_.
  ``FirmwareImage.file`` was configured to use ``PrivateFileSystemStorage``,
  which made it impossible to use other private storage backends.
  The `"OPENWISP_FIRMWARE_PRIVATE_STORAGE_INSTANCE"
  <https://github.com/openwisp/openwisp-firmware-upgrader#openwisp_firmware_private_storage_instance>`_
  setting is added to make the ``FirmwareImage.file`` storage configurable.
- Fixed `inconsistent URL keyword argument in "serve_private_file"
  URL pattern <https://github.com/openwisp/openwisp-firmware-upgrader/issues/197>`_.
  This broke the reverse proxy feature of `django-private-storage
  <https://github.com/edoburu/django-private-storage>`_.

Version 1.0.0 [2022-05-05]
--------------------------

Features
--------

- Added ``version`` and ``os`` filters to the ``build`` endpoint
- Added OpenWISP 1.x firmware upgrader (legacy)
- Added support backfire in upgrades from OpenWISP 1.x (legacy)
- Added functionality in OpenWrt backend to free up memory before
  uploading the firmware image
- Added following firmwares to the default firmware image map:

  - Custom WAP-1200
  - COMFAST CF-E320N v2 (OpenWRT 19.07 and earlier)
  - EnGenius EAP1300
  - Linksys WRT1900ACS
  - Linksys WRT3200ACM
  - Raspberry Pi 2 Model B
  - Raspberry Pi 3 Model B
  - TP-Link Archer C7 v1 (OpenWRT 19.07 and earlier)
  - TP-Link Archer C7 v1 (OpenWRT 19.07 and later)
  - TP-Link Archer C7 v2 (OpenWRT 19.07 and earlier)
  - TP-Link Archer C7 v2 (OpenWRT 19.07 and later)
  - TP-Link Archer C7 v4 (OpenWRT 19.07 and earlier)
  - TP-Link Archer C7 v4 (OpenWRT 19.07 and later)
  - TP-Link Archer C7 v5 (OpenWRT 19.07 and earlier)
  - TP-Link Archer C7 v5 (OpenWRT 19.07 and later)
  - TP-Link Archer C50 v4
  - TP-LINK CPE210 v3 (OpenWRT 19.07 and earlier)
  - TP-LINK CPE210 v2 (OpenWRT 19.07 and later)
  - TP-LINK CPE210 v3 (OpenWRT 19.07 and later)
  - TP-LINK CPE510 v3 (OpenWRT 19.07 and later)
  - TP-Link WDR3600 v1 (OpenWRT 19.07 and earlier)
  - TP-Link WDR3600 v1 (OpenWRT 19.07 and later)
  - TP-Link WDR4300 v1 (OpenWRT 19.07 and earlier)
  - TP-Link WDR4300 v1 (OpenWRT 19.07 and later)
  - TP-Link WDR4300 v1 Israel Version (OpenWRT 19.07 and earlier)
  - TP-Link WDR4300 v1 Israel Version (OpenWRT 19.07 and later)
  - TP-Link WR2543N/ND (OpenWRT 19.07 and earlier)
  - TP-Link WR2543N/ND (OpenWRT 19.07 and later)
  - TP-Link TL-WR902AC v3
  - Ubiquiti AirRouter (OpenWRT 19.07 and earlier)
  - Ubiquiti AirRouter (OpenWRT 19.07 and later)
  - Ubiquiti EdgeRouter Lite
  - Ubiquiti Nanostation Loco M2 - XW (OpenWRT 19.07 and earlier)
  - Ubiquiti Nanostation Loco M (OpenWRT 19.07 and later)
  - Ubiquiti Nanostation Loco M - XW (OpenWRT 19.07 and later)
  - Ubiquiti Nanostation M - XW (OpenWRT 19.07 and earlier)
  - Ubiquiti Nanostation M (OpenWRT 19.07 and earlier)
  - Ubiquiti Nanostation M - XW (OpenWRT 19.07 and later)
  - Ubiquiti Nanostation M (OpenWRT 19.07 and later)
  - Ubiquiti Picostation Bullet XW (OpenWRT 19.07 and earlier)
  - Ubiquiti Picostation M2HP & Bullet (OpenWRT 19.07 and earlier)
  - Ubiquiti Picostation M (OpenWRT 19.07 and later)
  - Ubiquiti Unifi AC Mesh (OpenWRT 19.07 and earlier)
  - Ubiquiti Unifi AC Mesh (OpenWRT 19.07 and later)
  - Ubiquiti Unifi AC Mesh-Pro (OpenWRT 19.07 and earlier)
  - Ubiquiti Unifi AC Mesh-Pro (OpenWRT 19.07 and later)
  - Ubiquiti UniFi AC Pro (OpenWRT 19.07 and later)
  - VMware, Inc. VMware Virtual Platform
  - ZBT-WG3526 (16M)
  - x86 32 bit (various models)
  - x86 Geode(TM) Integrated Processor by AMD

Changes
-------

Backward incompatible changes
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

- REST APIs are enabled by default. You can disable them by setting
  ``OPENWISP_FIRMWARE_UPGRADER_API`` to ``False``.
- Changed REST API prefix from ``/upgrader/`` to ``/firmware-upgrader/``.
  This makes it consistent with REST API endpoints of other modules

Dependencies
^^^^^^^^^^^^

- Dropped support for Python 3.6
- Dropped support for Django 2.2
- Added support for Python 3.8 and 3.9
- Added support for Django 3.2 and 4.0
- Upgraded openwisp-controller to 1.0.x

Other changes
^^^^^^^^^^^^^

- Avoid deletion of ``UpgradeOperation`` when related
  ``Firmware Image`` is deleted
- Increased default retries in OpenWRT upgrader from
  ``15`` to ``40``
- Made firmware upgrade logs translatable
- Changed the default API throttle rate from ``400/hour`` to ``1000/minute``
- Added time limits to ``openwisp_firmware_upgrader.tasks.create_device_firmware``
  and ``openwisp_firmware_upgrader.tasks.create_all_device_firmwares`` celery tasks

Bugfixes
--------

- Fixed firmware checksum check
- Improved error handling for upgrade operations
- Remove openwisp-config persistent checksum:
  openwisp-config 0.6.0 makes the checksum persistent,
  but this causes upgraded devices to not download the configuration
  again after the upgrade, which is an issue if the configuration
  contains any file which is not stored in ``/etc/``.
- Fixed a bug which caused ``Server 500`` error on creating a new
  ``Build`` object if ``category`` field was left empty
- Fixed bugs in restoring deleted devices using ``django-reversion``
- Fixed migrations referencing non-swappable OpenWISP modules
  that broke OpenWISP's extensibility

Version 0.1.1 [2021-01-08]
--------------------------

- [fix] Fixed ``os_identifier`` validation bug in ``Build`` model.

Version 0.1.0 [2020-11-27]
--------------------------

First release.
