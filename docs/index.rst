OpenWISP Firmware Upgrader
==========================

.. warning::

  This is the latest version


Firmware upgrade module of OpenWISP.

.. rubric:: Features

- Stores information of each upgrade operation which can be seen from the device page
- Automatic retries for recoverable failures
  (eg: firmware image upload issues because of intermittent internet connection)
- Performs a final check to find out if the upgrade completed successfully or not
- Prevents accidental multiple upgrades using the same firmware image
- Single device upgrade
- Mass upgrades
- Possibility to divide firmware images in categories
- `REST API <#rest-api>`__
- `Possibility of writing custom upgraders <#writing-custom-firmware-upgrader-classes>`_ for other
  firmware OSes or for custom OpenWRT based firmwares
- Configurable timeouts
- `Extensible <#extending-openwisp-firmware-upgrader>`_

.. image:: https://raw.githubusercontent.com/openwisp/openwisp2-docs/master/assets/design/openwisp-logo-black.svg
  :target: http://openwisp.org

.. toctree::
    :maxdepth: 1


    user/Quickstart.rst
    user/automatic-device-firmware-detection.rst
    user/custom-firmware-upgrader.rst
    user/rest-api.rst
    user/settings.rst
    developer/developer-docs.rst

