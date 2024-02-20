openwisp-firmware-upgrader
==========================

.. image:: https://github.com/openwisp/openwisp-firmware-upgrader/workflows/OpenWISP%20Firmware%20Upgrader%20CI%20Build/badge.svg?branch=master
   :target: https://github.com/openwisp/openwisp-firmware-upgrader/actions?query=OpenWISP+Firmware+Upgrader+CI+Build

.. image:: https://coveralls.io/repos/openwisp/openwisp-firmware-upgrader/badge.svg
  :target: https://coveralls.io/r/openwisp/openwisp-firmware-upgrader

.. image:: https://img.shields.io/librariesio/release/github/openwisp/openwisp-firmware-upgrader
  :target: https://libraries.io/github/openwisp/openwisp-firmware-upgrader#repository_dependencies
  :alt: Dependency monitoring

.. image:: https://img.shields.io/gitter/room/nwjs/nw.js.svg?style=flat-square
   :target: https://gitter.im/openwisp/general
   :alt: support chat

.. image:: https://badge.fury.io/py/openwisp-firmware-upgrader.svg
  :target: http://badge.fury.io/py/openwisp-firmware-upgrader
  :alt: Pypi Version

.. image:: https://pepy.tech/badge/openwisp-firmware-upgrader
  :target: https://pepy.tech/project/openwisp-firmware-upgrader
  :alt: Downloads

.. image:: https://img.shields.io/badge/code%20style-black-000000.svg
   :target: https://pypi.org/project/black/
   :alt: code style: black

------------

**Need a quick overview?** `Try the OpenWISP Demo <https://openwisp.org/demo.html>`_.

Firmware upgrade module of OpenWISP.

**Features**:

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

**For a more complete overview of the OpenWISP modules and architecture**,
see the
`OpenWISP Architecture Overview
<https://openwisp.io/docs/general/architecture.html>`_.

**Want to help OpenWISP?** `Find out how to help us grow here
<http://openwisp.io/docs/general/help-us.html>`_.

------------

.. contents:: **Table of Contents**:
   :backlinks: none
   :depth: 3

------------

Contributing
------------

Please refer to the `OpenWISP contributing guidelines <http://openwisp.io/docs/developer/contributing.html>`_.

Support
-------

See `OpenWISP Support Channels <http://openwisp.org/support.html>`_.

Changelog
---------

See `CHANGES <https://github.com/openwisp/openwisp-firmware-upgrader/blob/master/CHANGES.rst>`_.

License
-------

See `LICENSE <https://github.com/openwisp/openwisp-firmware-upgrader/blob/master/LICENSE>`_.
