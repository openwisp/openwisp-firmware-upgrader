Firmware Upgrader: Features
===========================

- Stores information of each upgrade operation which can be seen from the
  device page
- Automatic retries for recoverable failures (e.g.: firmware image upload
  issues because of intermittent internet connection)
- Performs a final check to find out if the upgrade completed successfully
  or not
- Prevents accidental multiple upgrades using the same firmware image
- Single device upgrade
- Mass upgrades
- Possibility to divide firmware images in categories
- :doc:`REST API <rest-api>`
- :doc:`Possibility of writing custom upgraders
  <custom-firmware-upgrader>` for other firmware OSes or for custom
  OpenWrt based firmwares
- Configurable timeouts
