Automatic Device Firmware Detection
===================================

*OpenWISP Firmware Upgrader* maintains a data structure for mapping the
firmware image files to board names called ``OPENWRT_FIRMWARE_IMAGE_MAP``.

Here is an example firmware image item from ``OPENWRT_FIRMWARE_IMAGE_MAP``

.. code-block:: python

    {
        # Firmware image file name.
        "ar71xx-generic-cf-e320n-v2-squashfs-sysupgrade.bin": {
            # Human readable name of the model which is displayed on
            # the UI
            "label": "COMFAST CF-E320N v2 (OpenWrt 19.07 and earlier)",
            # Tupe of board names with which the different versions
            # of the hardware are identified on OpenWrt
            "boards": ("COMFAST CF-E320N v2",),
        }
    }

When a device registers on OpenWISP, the :doc:`openwisp-config agent
</openwrt-config-agent/index>` reads the device board name from
`/tmp/sysinfo/model` and sends it to OpenWISP. This value is then saved in
the ``Device.model`` field. *OpenWISP Firmware Upgrader* uses this field
to automatically detect the correct firmware image for the device.

Use the :ref:`OPENWISP_CUSTOM_OPENWRT_IMAGES
<openwisp_custom_openwrt_images>` setting to add additional firmware image
in your project.
