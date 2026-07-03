Automatic Device Firmware Detection
===================================

When a firmware image is uploaded to a build, *OpenWISP Firmware Upgrader*
automatically extracts its metadata, including the board name, compatible
strings, target architecture, and firmware version. If the fwtool metadata
trailer embedded by the OpenWrt build system is found, it is used as the
primary source. Otherwise, the extractor falls back to scanning the kernel
for a Device Tree Blob (DTB).

When a device registers on OpenWISP, the :doc:`openwisp-config agent
</openwrt-config-agent/index>` reads the device board name from
``/temp/sysinfo/model`` and sends it to OpenWISP. This value is saved in
the ``Device.model`` field, *OpenWISP Firmware Upgrader* uses this field
to automatically pair devices with the firmware image whose ``board``
matches ``Device.model`` and whose build's **OS identifier** matches the
device's ``os`` field.
