Automatic Device Firmware Detection
===================================

When a firmware image is uploaded to a build, *OpenWISP Firmware Upgrader*
automatically extracts its metadata, including the board name, compatible
strings, target architecture, and firmware version. If the fwtool metadata
trailer embedded by the OpenWrt build system is found, it is used as the
primary source for the target, firmware version, board identifier, and
compatible strings.

The kernel is then also scanned for a Device Tree Blob (DTB), even when
fwtool succeeded. If the DTB reports a device model, it replaces fwtool's
board identifier (a machine-readable value, e.g. ``tplink_archer-c6-v3``)
with the human-readable model devices report at runtime (e.g. ``TP-Link
Archer C6 v3``), which pairing matches against ``Device.model``. The DTB
scan also fills in the ``compatible`` field if fwtool did not provide one.

If the fwtool trailer is missing entirely, the DTB scan is used as a full
fallback instead, providing the board and compatible strings; target and
firmware version cannot be determined this way and must be entered
manually.

When a device registers on OpenWISP, the :doc:`openwisp-config agent
</openwrt-config-agent/index>` reads the device board name from
``/tmp/sysinfo/model`` and sends it to OpenWISP. This value is saved in
the ``Device.model`` field. *OpenWISP Firmware Upgrader* uses this field
to automatically pair devices with the firmware image whose ``board``
matches ``Device.model`` and whose build's **OS identifier** matches the
device's ``os`` field.

Pairing happens once an image's metadata extraction has completed: whether
it succeeded fully, succeeded only partially (i.e. with status
*Incomplete*), or was confirmed manually. Images still being processed, or
for which extraction failed, are not paired automatically. Images that
declare a compatibility version greater than ``1.0`` are never paired
automatically, regardless of extraction status; assign them to a device
manually from the device's *Firmware* tab instead.
