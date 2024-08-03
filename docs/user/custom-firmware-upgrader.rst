Writing Custom Firmware Upgrader Classes
========================================

You can write custom upgraders for other firmware OSes or for custom
OpenWrt based firmwares.

Here is an example custom OpenWrt firmware upgrader class:

.. code-block:: python

    from openwisp_firmware_upgrader.upgraders.openwrt import OpenWrt


    class CustomOpenWrtBasedFirmware(OpenWrt):
        # this firmware uses a custom upgrade command
        UPGRADE_COMMAND = "upgrade_firmware.sh --keep-config"
        # it takes somewhat more time to boot so it needs more time
        RECONNECT_DELAY = 150
        RECONNECT_RETRY_DELAY = 5
        RECONNECT_MAX_RETRIES = 20

        def get_remote_path(self, image):
            return "/tmp/firmware.img"

        def get_upgrade_command(self, path):
            return self.UPGRADE_COMMAND

You will need to place your custom upgrader class on the python path of
your application and then add this path to the
:ref:`OPENWISP_FIRMWARE_UPGRADERS_MAP <openwisp_firmware_upgraders_map>`
setting.
