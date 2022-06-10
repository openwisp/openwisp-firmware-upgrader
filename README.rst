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

Installation instructions
-------------------------

Requirements
~~~~~~~~~~~~

- Python >= 3.7
- openwisp-controller (and its dependencies) >= 1.0.0

Install Dependencies
~~~~~~~~~~~~~~~~~~~~

Install spatialite and sqlite:

.. code-block:: shell

    sudo apt-get install sqlite3 libsqlite3-dev openssl libssl-dev
    sudo apt-get install gdal-bin libproj-dev libgeos-dev libspatialite-dev

Setup (integrate in an existing Django project)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Follow the `setup instructions of openwisp-controller
<https://github.com/openwisp/openwisp-controller#setup-integrate-in-an-existing-django-project>`_, then add the settings described below.

.. code-block:: python

    INSTALLED_APPS = [
        # django apps
        # all-auth
        'django.contrib.sites',
        'openwisp_users.accounts',
        'allauth',
        'allauth.account',
        'django_extensions',
        'private_storage',
        # openwisp2 modules
        'openwisp_controller.pki',
        'openwisp_controller.config',
        'openwisp_controller.connection',
        'openwisp_controller.geo',
        'openwisp_firmware_upgrader',
        'openwisp_users',
        'openwisp_notifications',
        'openwisp_ipam',
        # openwisp2 admin theme (must be loaded here)
        'openwisp_utils.admin_theme',
        # admin
        'django.contrib.admin',
        'django.forms',
        # other dependencies
        'sortedm2m',
        'reversion',
        'leaflet',
        'flat_json_widget',
        # rest framework
        'rest_framework',
        'rest_framework.authtoken',
        'rest_framework_gis',
        'django_filters',
        'drf_yasg',
        # channels
        'channels',
    ]

    MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
    PRIVATE_STORAGE_ROOT = os.path.join(MEDIA_ROOT, 'firmware')

The root URLconf (``urls.py``) should look like the following example:

.. code-block:: python

    from django.conf import settings
    from django.contrib import admin
    from django.conf.urls import include, url
    from django.contrib.staticfiles.urls import staticfiles_urlpatterns

    urlpatterns = [
        path('admin/', admin.site.urls),
        path('', include('openwisp_controller.urls')),
        path('', redirect_view, name='index'),
        path('', include('openwisp_firmware_upgrader.urls')),
        path('api/v1/', include((get_api_urls(), 'users'), namespace='users')),
        path('api/v1/', include('openwisp_utils.api.urls')),
    ]

    urlpatterns += staticfiles_urlpatterns()

Installing for development
~~~~~~~~~~~~~~~~~~~~~~~~~~

Install your forked repo:

.. code-block:: shell

    git clone git://github.com/<your_fork>/openwisp-firmware-upgrader
    cd openwisp-firmware-upgrader/
    python setup.py develop

Install test requirements:

.. code-block:: shell

    pip install -r requirements-test.txt

Create database:

.. code-block:: shell

    cd tests/
    ./manage.py migrate
    ./manage.py createsuperuser

Launch development server:

.. code-block:: shell

    ./manage.py runserver 0.0.0.0:8000

You can access the admin interface at http://127.0.0.1:8000/admin/.

Run celery and celery-beat with the following commands
(separate terminal windows are needed):

.. code-block:: shell

    # (cd tests)
    celery -A openwisp2 worker -l info
    celery -A openwisp2 beat -l info

Run tests with:

.. code-block:: shell

    # run qa checks
    ./run-qa-checks

    # standard tests
    ./runtests.py

    # tests for the sample app
    SAMPLE_APP=1 ./runtests.py --keepdb --failfast

When running the last line of the previous example, the environment variable
``SAMPLE_APP`` activates the app in ``/tests/openwisp2/sample_firmware_upgrader/``
which is a simple django app that extends ``openwisp-firmware-upgrader`` with
the sole purpose of testing its extensibility, for more information regarding
this concept, read the following section.

Quickstart Guide
----------------

Requirements:

- Devices running at least OpenWRT 12.09 Attitude Adjustment, older versions
  of OpenWRT have not worked at all in our tests
- Devices must have enough free RAM to be able to upload the
  new image to ``/tmp``

1. Create a category
~~~~~~~~~~~~~~~~~~~~

Create a category for your firmware images
by going to *Firmware management > Firmware categories > Add firmware category*,
if you use only one firmware type in your network, you could simply
name the category "default" or "standard".

.. image:: https://raw.githubusercontent.com/openwisp/openwisp-firmware-upgrader/docs/docs/images/quickstart-category.gif

If you use multiple firmware images with different features, create one category
for each firmware type, eg:

- WiFi
- SDN router
- LoRa Gateway

This is necessary in order to perform mass upgrades only on specific
firmware categories when, for example, a new *LoRa Gateway* firmware becomes available.

2. Create the build object
~~~~~~~~~~~~~~~~~~~~~~~~~~

Create a build a build object by going to
*Firmware management > Firmware builds > Add firmware build*,
the build object is related to a firmware category and is the collection of the
different firmware images which have been compiled for the different hardware models
supported by the system.

The version field indicates the firmware version, the change log field is optional but
we recommend filling it to help operators know the differences between each version.

.. image:: https://raw.githubusercontent.com/openwisp/openwisp-firmware-upgrader/docs/docs/images/quickstart-build.gif

An important but optional field of the build model is **OS identifier**, this field
should match the value of the **Operating System** field which gets automatically filled
during device registration, eg: ``OpenWrt 19.07-SNAPSHOT r11061-6ffd4d8a4d``.
It is used by the firmware-upgrader module to automatically
create ``DeviceFirmware`` objects for existing devices or when new devices register.
A ``DeviceFirmware`` object represent the relationship between a device and a firmware image,
it basically tells us which firmware image is installed on the device.

To find out the exact value to use, you should either do a
test flash on a device and register it to the system or you should inspect the firmware image
by decompressing it and find the generated value in the firmware image.

If you're not sure about what **OS identifier** to use, just leave it empty, you can fill
it later on when you find out.

Now save the build object to create it.

3. Upload images to the build
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Now is time to add images to the build, we suggest adding one image at time.
Alternatively the `REST API <#rest-api>`__ can be used to automate this step.

.. image:: https://raw.githubusercontent.com/openwisp/openwisp-firmware-upgrader/docs/docs/images/quickstart-firmwareimage.gif

If you use a hardware model which is not listed in the image types, if the
hardware model is officially supported by OpenWRT, you can send us a pull-request to add it,
otherwise you can use `the setting OPENWISP_CUSTOM_OPENWRT_IMAGES <#openwisp_custom_openwrt_images>`__
to add it.

4. Perform a firmware upgrade to a specific device
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. image:: https://raw.githubusercontent.com/openwisp/openwisp-firmware-upgrader/docs/docs/images/quickstart-devicefirmware.gif

Once a new build is ready, has been created in the system and its image have been uploaded,
it will be the time to finally upgrade our devices.

To perform the upgrade of a single device, navigate to the device details,
then go to the "Firmware" tab.

If you correctly filled **OS identifier** in step 2, you should have a situation
similar to the one above: in this example, the device is using version ``1.0``
and we want to upgrade it to version ``2.0``, once the new firmware image
is selected we just have to hit save, then a new tab will appear in the device page
which allows us to see what's going on during the upgrade.

Right now, the update of the upgrade information is not asynchronous yet, so you will
have to reload the page periodically to find new information. This will be addressed
in a future release.

5. Performing mass upgrades
~~~~~~~~~~~~~~~~~~~~~~~~~~~

First of all, please ensure the following preconditions are met:

- the system is configured correctly
- the new firmware images are working as expected
- you already tried the upgrade of single devices several times.

At this stage you can try a mass upgrade by doing the following:

- go to the build list page
- select the build which contains the latest firmware images you
  want the devices to be upgraded with
- click on "Mass-upgrade devices related to the selected build".

.. image:: https://raw.githubusercontent.com/openwisp/openwisp-firmware-upgrader/docs/docs/images/quickstart-batch-upgrade.gif

At this point you should see a summary page which will inform you of which devices
are going to be upgraded, you can either confirm the operation or cancel.

Once the operation is confirmed you will be redirected to a page in which you
can monitor the progress of the upgrade operations.

Right now, the update of the upgrade information is not asynchronous yet, so you will
have to reload the page periodically to find new information. This will be addressed
in a future release.

Automatic device firmware detection
-----------------------------------

*OpenWISP Firmware Upgrader* maintains a data structure for mapping
the firmware image files to board names called ``OPENWRT_FIRMWARE_IMAGE_MAP``.

Here is an example firmware image item from ``OPENWRT_FIRMWARE_IMAGE_MAP``

.. code-block:: python

    {
        # Firmware image file name.
        'ar71xx-generic-cf-e320n-v2-squashfs-sysupgrade.bin': {
            # Human readable name of the model which is displayed on
            # the UI
            'label': 'COMFAST CF-E320N v2 (OpenWRT 19.07 and earlier)',
            # Tupe of board names with which the different versions
            # of the hardware are identified on OpenWrt
            'boards': ('COMFAST CF-E320N v2',),
        }
    }

When a device registers on OpenWISP, the `openwisp-config agent
<https://github.com/openwisp/openwisp-config#openwisp-config>`_
read the device board name from `/tmp/sysinfo/model` and sends it to OpenWISP.
This value is then saved in the ``Device.model`` field.
*OpenWISP Firmware Upgrader* uses this field to automatically detect
the correct firmware image for the device.

Use the `OPENWISP_CUSTOM_OPENWRT_IMAGES <#openwisp_custom_openwrt_images>`_
setting to add additional firmware image in your project.

Writing Custom Firmware Upgrader Classes
----------------------------------------

You can write custom upgraders for other firmware OSes or for
custom OpenWrt based firmwares.

Here is an example custom OpenWrt firmware upgrader class:

.. code-block:: python

    from openwisp_firmware_upgrader.upgraders.openwrt import OpenWrt

    class CustomOpenWrtBasedFirmware(OpenWrt):
        # this firmware uses a custom upgrade command
        UPGRADE_COMMAND = 'upgrade_firmware.sh --keep-config'
        # it takes somewhat more time to boot so it needs more time
        RECONNECT_DELAY = 150
        RECONNECT_RETRY_DELAY = 5
        RECONNECT_MAX_RETRIES = 20

        def get_remote_path(self, image):
            return '/tmp/firmware.img'

        def get_upgrade_command(self, path):
            return self.UPGRADE_COMMAND

You will need to place your custom upgrader class on the python path
of your application and then add this path to the `OPENWISP_FIRMWARE_UPGRADERS_MAP
<#openwisp_firmware_upgraders_map>`_ setting.

REST API
--------

To enable the API the setting
`OPENWISP_FIRMWARE_UPGRADER_API <#openwisp-firmware-upgrader-api>`_
must be set to ``True``.

Live documentation
~~~~~~~~~~~~~~~~~~

.. image:: https://raw.githubusercontent.com/openwisp/openwisp-firmware-upgrader/docs/docs/images/api-docs.png

A general live API documentation (following the OpenAPI specification) at ``/api/v1/docs/``.

Browsable web interface
~~~~~~~~~~~~~~~~~~~~~~~

.. image:: https://raw.githubusercontent.com/openwisp/openwisp-firmware-upgrader/docs/docs/images/api-ui.png

Additionally, opening any of the endpoints `listed below <#list-of-endpoints>`_
directly in the browser will show the `browsable API interface of Django-REST-Framework
<https://www.django-rest-framework.org/topics/browsable-api/>`_,
which makes it even easier to find out the details of each endpoint.

Authentication
~~~~~~~~~~~~~~

See openwisp-users: `authenticating with the user token
<https://github.com/openwisp/openwisp-users#authenticating-with-the-user-token>`_.

When browsing the API via the `Live documentation <#live-documentation>`_
or the `Browsable web page <#browsable-web-interface>`_, you can also use
the session authentication by logging in the django admin.

Pagination
~~~~~~~~~~

All *list* endpoints support the ``page_size`` parameter that allows paginating
the results in conjunction with the ``page`` parameter.

.. code-block:: text

    GET /api/v1/firmware-upgrader/build/?page_size=10
    GET /api/v1/firmware-upgrader/build/?page_size=10&page=2

Filtering by organization slug
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Most endpoints allow to filter by organization slug, eg:

.. code-block:: text

    GET /api/v1/firmware-upgrader/build/?organization=org-slug

List of endpoints
~~~~~~~~~~~~~~~~~

Since the detailed explanation is contained in the `Live documentation <#live-documentation>`_
and in the `Browsable web page <#browsable-web-interface>`_ of each point,
here we'll provide just a list of the available endpoints,
for further information please open the URL of the endpoint in your browser.

List mass upgrade operations
############################

.. code-block:: text

    GET /api/v1/firmware-upgrader/batch-upgrade-operation/

Get mass upgrade operation detail
#################################

.. code-block:: text

    GET /api/v1/firmware-upgrader/batch-upgrade-operation/{id}/

List firmware builds
####################

.. code-block:: text

    GET /api/v1/firmware-upgrader/build/

Create firmware build
#####################

.. code-block:: text

    POST /api/v1/firmware-upgrader/build/

Get firmware build details
##########################

.. code-block:: text

    GET /api/v1/firmware-upgrader/build/{id}/

Change details of firmware build
################################

.. code-block:: text

    PUT /api/v1/firmware-upgrader/build/{id}/

Patch details of firmware build
###############################

.. code-block:: text

    PATCH /api/v1/firmware-upgrader/build/{id}/

Delete firmware build
#####################

.. code-block:: text

    DELETE /api/v1/firmware-upgrader/build/{id}/

Get list of images of a firmware build
######################################

.. code-block:: text

    GET /api/v1/firmware-upgrader/build/{id}/image/

Upload new firmware image to the build
######################################

.. code-block:: text

    POST /api/v1/firmware-upgrader/build/{id}/image/

Get firmware image details
##########################

.. code-block:: text

    GET /api/v1/firmware-upgrader/build/{build_pk}/image/{id}/

Delete firmware image
#####################

.. code-block:: text

    DELETE /api/v1/firmware-upgrader/build/{build_pk}/image/{id}/

Download firmware image
#######################

.. code-block:: text

    GET /api/v1/firmware-upgrader/build/{build_pk}/image/{id}/download/

Perform batch upgrade
#####################

Upgrades all the devices related to the specified build ID.

.. code-block:: text

    POST /api/v1/firmware-upgrader/build/{id}/upgrade/

Dry-run batch upgrade
#####################

Returns a list representing the ``DeviceFirmware`` and ``Device``
instances that would be upgraded if POST is used.

``Device`` objects are indicated only when no ``DeviceFirmware``
object exists for a device which would be upgraded.

.. code-block:: text

    GET /api/v1/firmware-upgrader/build/{id}/upgrade/

List firmware categories
########################

.. code-block:: text

    GET /api/v1/firmware-upgrader/category/

Create new firmware category
############################

.. code-block:: text

    POST /api/v1/firmware-upgrader/category/

Get firmware category details
#############################

.. code-block:: text

    GET /api/v1/firmware-upgrader/category/{id}/

Change the details of a firmware category
#########################################

.. code-block:: text

    PUT /api/v1/firmware-upgrader/category/{id}/

Patch the details of a firmware category
########################################

.. code-block:: text

    PATCH /api/v1/firmware-upgrader/category/{id}/

Delete a firmware category
##########################

.. code-block:: text

    DELETE /api/v1/firmware-upgrader/category/{id}/

Settings
--------

``OPENWISP_FIRMWARE_UPGRADER_RETRY_OPTIONS``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

+--------------+--------------+
| **type**:    | ``dict``     |
+--------------+--------------+
| **default**: | see below    |
+--------------+--------------+

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
(eg: because of a network issue during the upload of the image),
the upgrade operation will be retried 4 more times with an exponential
random backoff and a maximum delay of 10 minutes.

For more information regarding these settings, consult the `celery documentation
regarding automatic retries for known errors
<https://docs.celeryproject.org/en/stable/userguide/tasks.html#automatic-retry-for-known-exceptions>`_.

``OPENWISP_FIRMWARE_UPGRADER_TASK_TIMEOUT``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

+--------------+--------------+
| **type**:    | ``int``      |
+--------------+--------------+
| **default**: | ``600``      |
+--------------+--------------+

Timeout for the background tasks which perform firmware upgrades.

If for some unexpected reason an upgrade remains stuck for more than 10 minutes,
the upgrade operation will be flagged as failed and the task will be killed.

This should not happen, but a global task time out is a best practice when
using background tasks because it prevents the situation in which an unexpected
bug causes a specific task to hang, which will quickly fill all the available
slots in a background queue and prevent other tasks from being executed, which
will end up affecting negatively the rest of the application.

``OPENWISP_CUSTOM_OPENWRT_IMAGES``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

+--------------+-------------+
| **type**:    | ``tuple``   |
+--------------+-------------+
| **default**: | ``None``    |
+--------------+-------------+

This setting can be used to extend the list of firmware image types
included in *OpenWISP Firmware Upgrader*. This setting is suited to
add support for custom OpenWrt images.

.. code-block:: python

    OPENWISP_CUSTOM_OPENWRT_IMAGES = (
        (
            # Firmware image file name.
            'customimage-squashfs-sysupgrade.bin', {
                # Human readable name of the model which is displayed on
                # the UI
                'label': 'Custom WAP-1200',
                # Tuple of board names with which the different versions of
                # the hardware are identified on OpenWrt
                'boards': ('CWAP1200',)
            }
        ),
    )

Kindly read `"Automatic detection of firmware of device"
<#automatic-device-firmware-detection>`_
section of this documentation to know how *OpenWISP Firmware Upgrader*
uses this setting in upgrades.

``OPENWISP_FIRMWARE_UPGRADER_MAX_FILE_SIZE``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

+--------------+------------------------------+
| **type**:    | ``int``                      |
+--------------+------------------------------+
| **default**: | ``30 * 1024 * 1024`` (30 MB) |
+--------------+------------------------------+

This setting can be used to set the maximum size limit for firmware images, eg:

.. code-block:: python

    OPENWISP_FIRMWARE_UPGRADER_MAX_FILE_SIZE = 40 * 1024 * 1024  # 40MB

**Notes**:

- Value must be specified in bytes. ``None`` means unlimited.

``OPENWISP_FIRMWARE_UPGRADER_API``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

+--------------+-----------+
| **type**:    | ``bool``  |
+--------------+-----------+
| **default**: | ``True``  |
+--------------+-----------+

Indicates whether the API for Firmware Upgrader is enabled or not.

``OPENWISP_FIRMWARE_UPGRADER_OPENWRT_SETTINGS``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

+--------------+-----------+
| **type**:    | ``dict``  |
+--------------+-----------+
| **default**: | ``{}``    |
+--------------+-----------+

Allows changing the default OpenWRT upgrader settings, eg:

.. code-block:: python

    OPENWISP_FIRMWARE_UPGRADER_OPENWRT_SETTINGS = {
        'reconnect_delay': 120,
        'reconnect_retry_delay': 20,
        'reconnect_max_retries': 15,
        'upgrade_timeout': 90,
    }

- ``reconnect_delay``: amount of seconds to wait before trying to connect
  again to the device after the upgrade command has been launched;
  the re-connection step is necessary to verify the upgrade has completed successfully;
  defaults to ``120`` seconds
- ``reconnect_retry_delay``: amount of seconds to wait after a
  re-connection attempt has failed;
  defaults to ``20`` seconds
- ``reconnect_max_retries``: maximum re-connection attempts
  defaults to ``15`` attempts
- ``upgrade_timeout``: amount of seconds before the shell session
  is closed after the upgrade command is launched on the device,
  useful in case  the upgrade command hangs (it happens on older OpenWRT versions);
  defaults to ``90`` seconds

``OPENWISP_FIRMWARE_API_BASEURL``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

+--------------+-----------------------------------+
| **type**:    | ``dict``                          |
+--------------+-----------------------------------+
| **default**: |  ``/`` (points to same server)    |
+--------------+-----------------------------------+

If you have a seperate instance of openwisp-firmware-upgrader API on a
different domain, you can use this option to change the base of the image
download url, this will enable you to point to your API server's domain,
example value: ``https://myfirmware.myapp.com``.

``OPENWISP_FIRMWARE_UPGRADERS_MAP``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

+--------------+-------------------------------------------------------------------------------------------------------------------------------+
| **type**:    | ``dict``                                                                                                                      |
+--------------+-------------------------------------------------------------------------------------------------------------------------------+
| **default**: | .. code-block:: python                                                                                                        |
|              |                                                                                                                               |
|              |   {                                                                                                                           |
|              |     'openwisp_controller.connection.connectors.openwrt.ssh.OpenWrt': 'openwisp_firmware_upgrader.upgraders.openwrt.OpenWrt',  |
|              |   }                                                                                                                           |
+--------------+-------------------------------------------------------------------------------------------------------------------------------+

A dictionary that maps update strategies to upgraders.

If you want to use a custom update strategy you will need to use this setting
to provide an entry with the class path of your update strategy as the key.

If you need to use a `custom upgrader class <#writing-custom-firmware-upgrader-classes>`_
you will need to use this setting to provide an entry with the class path of your upgrader
as the value.

``OPENWISP_FIRMWARE_PRIVATE_STORAGE_INSTANCE``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

+--------------+-------------------------------------------------------------------------------------+
| **type**:    | ``str``                                                                             |
+--------------+-------------------------------------------------------------------------------------+
| **default**: |  ``openwisp_firmware_upgrader.private_storage.storage.file_system_private_storage`` |
+--------------+-------------------------------------------------------------------------------------+

Dotted path to an instance of any one of the storage classes in
`private_storage <https://github.com/edoburu/django-private-storage#django-private-storage>`_.
This instance is used to store firmware image files.

By default, an instance of ``private_storage.storage.files.PrivateFileSystemStorage``
is used.

Extending openwisp-firmware-upgrader
------------------------------------

One of the core values of the OpenWISP project is `Software Reusability <http://openwisp.io/docs/general/values.html#software-reusability-means-long-term-sustainability>`_,
for this reason *OpenWISP Firmware Upgrader* provides a set of base classes
which can be imported, extended and reused to create derivative apps.

In order to implement your custom version of *OpenWISP Firmware Upgrader*,
you need to perform the steps described in this section.

When in doubt, the code in the `test project <https://github.com/openwisp/openwisp-firmware-upgrader/tree/master/tests/openwisp2/>`_
and the `sample app <https://github.com/openwisp/openwisp-firmware-upgrader/tree/master/tests/openwisp2/sample_firmware_upgrader/>`_
will serve you as source of truth:
just replicate and adapt that code to get a basic derivative of
*OpenWISP Firmware Upgrader* working.

**Premise**: if you plan on using a customized version of this module,
we suggest to start with it since the beginning, because migrating your data
from the default module to your extended version may be time consuming.

1. Initialize your custom module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The first thing you need to do is to create a new django app which will
contain your custom version of *OpenWISP Firmware Upgrader*.

A django app is nothing more than a
`python package <https://docs.python.org/3/tutorial/modules.html#packages>`_
(a directory of python scripts), in the following examples we'll call this django app
``myupgrader``, but you can name it how you want::

    django-admin startapp myupgrader

Keep in mind that the command mentioned above must be called from a directory
which is available in your `PYTHON_PATH <https://docs.python.org/3/using/cmdline.html#envvar-PYTHONPATH>`_
so that you can then import the result into your project.

Now you need to add ``myupgrader`` to ``INSTALLED_APPS`` in your ``settings.py``,
ensuring also that ``openwisp_firmware_upgrader`` has been removed:

.. code-block:: python

    INSTALLED_APPS = [
        # ... other apps ...

        # 'openwisp_firmware_upgrader'  <-- comment out or delete this line
        'myupgrader'
    ]

For more information about how to work with django projects and django apps,
please refer to the `django documentation <https://docs.djangoproject.com/en/dev/intro/tutorial01/>`_.

2. Install ``openwisp-firmware-upgrader``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Install (and add to the requirement of your project) ``openwisp-firmware-upgrader``::

    pip install openwisp-firmware-upgrader

3. Add ``EXTENDED_APPS``
~~~~~~~~~~~~~~~~~~~~~~~~

Add the following to your ``settings.py``:

.. code-block:: python

    EXTENDED_APPS = ['openwisp_firmware_upgrader']

4. Add ``openwisp_utils.staticfiles.DependencyFinder``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Add ``openwisp_utils.staticfiles.DependencyFinder`` to
``STATICFILES_FINDERS`` in your ``settings.py``:

.. code-block:: python

    STATICFILES_FINDERS = [
        'django.contrib.staticfiles.finders.FileSystemFinder',
        'django.contrib.staticfiles.finders.AppDirectoriesFinder',
        'openwisp_utils.staticfiles.DependencyFinder',
    ]

5. Add ``openwisp_utils.loaders.DependencyLoader``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Add ``openwisp_utils.loaders.DependencyLoader`` to ``TEMPLATES`` in your ``settings.py``:

.. code-block:: python

    TEMPLATES = [
        {
            'BACKEND': 'django.template.backends.django.DjangoTemplates',
            'OPTIONS': {
                'loaders': [
                    'django.template.loaders.filesystem.Loader',
                    'django.template.loaders.app_directories.Loader',
                    'openwisp_utils.loaders.DependencyLoader',
                ],
                'context_processors': [
                    'django.template.context_processors.debug',
                    'django.template.context_processors.request',
                    'django.contrib.auth.context_processors.auth',
                    'django.contrib.messages.context_processors.messages',
                ],
            },
        }
    ]

6. Inherit the AppConfig class
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Please refer to the following files in the sample app of the test project:

- `sample_firmware_upgrader/__init__.py <https://github.com/openwisp/openwisp-firmware-upgrader/tree/master/tests/openwisp2/sample_firmware_upgrader/__init__.py>`_.
- `sample_firmware_upgrader/apps.py <https://github.com/openwisp/openwisp-firmware-upgrader/tree/master/tests/openwisp2/sample_firmware_upgrader/apps.py>`_.

You have to replicate and adapt that code in your project.

For more information regarding the concept of ``AppConfig`` please refer to
the `"Applications" section in the django documentation <https://docs.djangoproject.com/en/dev/ref/applications/>`_.

7. Create your custom models
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For the purpose of showing an example, we added a simple "details" field to the
`models of the sample app in the test project <https://github.com/openwisp/openwisp-firmware-upgrader/tree/master/tests/openwisp2/sample_firmware_upgrader/models.py>`_.

You can add fields in a similar way in your ``models.py`` file.

**Note**: for doubts regarding how to use, extend or develop models please refer to
the `"Models" section in the django documentation <https://docs.djangoproject.com/en/dev/topics/db/models/>`_.

8. Add swapper configurations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Once you have created the models, add the following to your ``settings.py``:

.. code-block:: python

    # Setting models for swapper module
    FIRMWARE_UPGRADER_CATEGORY_MODEL = 'myupgrader.Category'
    FIRMWARE_UPGRADER_BUILD_MODEL = 'myupgrader.Build'
    FIRMWARE_UPGRADER_FIRMWAREIMAGE_MODEL = 'myupgrader.FirmwareImage'
    FIRMWARE_UPGRADER_DEVICEFIRMWARE_MODEL = 'myupgrader.DeviceFirmware'
    FIRMWARE_UPGRADER_BATCHUPGRADEOPERATION_MODEL = 'myupgrader.BatchUpgradeOperation'
    FIRMWARE_UPGRADER_UPGRADEOPERATION_MODEL = 'myupgrader.UpgradeOperation'

Substitute ``myupgrader`` with the name you chose in step 1.

9. Create database migrations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Create and apply database migrations::

    ./manage.py makemigrations
    ./manage.py migrate

For more information, refer to the
`"Migrations" section in the django documentation <https://docs.djangoproject.com/en/dev/topics/migrations/>`_.

10. Create the admin
~~~~~~~~~~~~~~~~~~~~

Refer to the `admin.py file of the sample app <https://github.com/openwisp/openwisp-firmware-upgrader/tree/master/tests/openwisp2/sample_firmware_upgrader/admin.py>`_.

To introduce changes to the admin, you can do it in two main ways which are described below.

**Note**: for more information regarding how the django admin works, or how it can be customized,
please refer to `"The django admin site" section in the django documentation <https://docs.djangoproject.com/en/dev/ref/contrib/admin/>`_.

1. Monkey patching
##################

If the changes you need to add are relatively small, you can resort to monkey patching.

For example:

.. code-block:: python

    from openwisp_firmware_upgrader.admin import (  # noqa
        BatchUpgradeOperationAdmin,
        BuildAdmin,
        CategoryAdmin,
    )

    BuildAdmin.list_display.insert(1, 'my_custom_field')
    BuildAdmin.ordering = ['-my_custom_field']

2. Inheriting admin classes
###########################

If you need to introduce significant changes and/or you don't want to resort to
monkey patching, you can proceed as follows:

.. code-block:: python

    from django.contrib import admin
    from openwisp_firmware_upgrader.admin import (
        BatchUpgradeOperationAdmin as BaseBatchUpgradeOperationAdmin,
        BuildAdmin as BaseBuildAdmin,
        CategoryAdmin as BaseCategoryAdmin,
    )
    from openwisp_firmware_upgrader.swapper import load_model

    BatchUpgradeOperation = load_model('BatchUpgradeOperation')
    Build = load_model('Build')
    Category = load_model('Category')
    DeviceFirmware = load_model('DeviceFirmware')
    FirmwareImage = load_model('FirmwareImage')
    UpgradeOperation = load_model('UpgradeOperation')

    admin.site.unregister(BatchUpgradeOperation)
    admin.site.unregister(Build)
    admin.site.unregister(Category)

    class BatchUpgradeOperationAdmin(BaseBatchUpgradeOperationAdmin):
        # add your changes here

    class BuildAdmin(BaseBuildAdmin):
        # add your changes here

    class CategoryAdmin(BaseCategoryAdmin):
        # add your changes here

11. Create root URL configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Please refer to the `urls.py <https://github.com/openwisp/openwisp-firmware-upgrader/tree/master/tests/openwisp2/urls.py>`_
file in the test project.

For more information about URL configuration in django, please refer to the
`"URL dispatcher" section in the django documentation <https://docs.djangoproject.com/en/dev/topics/http/urls/>`_.

12. Create celery.py
~~~~~~~~~~~~~~~~~~~~

Please refer to the `celery.py <https://github.com/openwisp/openwisp-firmware-upgrader/tree/master/tests/openwisp2/celery.py>`_
file in the test project.

For more information about the usage of celery in django, please refer to the
`"First steps with Django" section in the celery documentation <https://docs.celeryproject.org/en/master/django/first-steps-with-django.html>`_.

13. Import the automated tests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When developing a custom application based on this module, it's a good
idea to import and run the base tests too, so that you can be sure the changes
you're introducing are not breaking some of the existing features of *OpenWISP Firmware Upgrader*.

In case you need to add breaking changes, you can overwrite the tests defined
in the base classes to test your own behavior.

See the `tests of the sample app <https://github.com/openwisp/openwisp-firmware-upgrader/blob/master/tests/openwisp2/sample_firmware_upgrader/tests.py>`_
to find out how to do this.

You can then run tests with::

    # the --parallel flag is optional
    ./manage.py test --parallel myupgrader

Substitute ``myupgrader`` with the name you chose in step 1.

For more information about automated tests in django, please refer to
`"Testing in Django" <https://docs.djangoproject.com/en/dev/topics/testing/>`_.

Other base classes that can be inherited and extended
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The following steps are not required and are intended for more advanced customization.

``FirmwareImageDownloadView``
#############################

This view controls how the firmware images are stored and who has permission to download them.

The full python path is: ``openwisp_firmware_upgrader.private_storage.FirmwareImageDownloadView``.

If you want to extend this view, you will have to perform the additional steps below.

Step 1. import and extend view:

.. code-block:: python

    # myupgrader/views.py
    from openwisp_firmware_upgrader.private_storage import (
        FirmwareImageDownloadView as BaseFirmwareImageDownloadView
    )

    class FirmwareImageDownloadView(BaseFirmwareImageDownloadView):
        # add your customizations here ...
        pass

Step 2: remove the following line from your root ``urls.py`` file:

.. code-block:: python

    path('firmware/', include('openwisp_firmware_upgrader.private_storage.urls')),

Step 3: add an URL route pointing to your custom view in ``urls.py`` file:

.. code-block:: python

    # urls.py
    from myupgrader.views import FirmwareImageDownloadView

    urlpatterns = [
        # ... other URLs
        path('<your-custom-path>', FirmwareImageDownloadView.as_view(), name='serve_private_file',),
    ]

For more information regarding django views, please refer to the
`"Class based views" section in the django documentation <https://docs.djangoproject.com/en/dev/topics/class-based-views/>`_.

API views
~~~~~~~~~

If you need to customize the behavior of the API views, the procedure to follow
is similar to the one described in
`FirmwareImageDownloadView <#firmwareimagedownloadview>`_,
with the difference that you may also want to create your own
`serializers <https://www.django-rest-framework.org/api-guide/serializers/>`_
if needed.

The API code is stored in
`openwisp_firmware_upgrader.api <https://github.com/openwisp/openwisp-firmware-upgrader/blob/master/openwisp_firmware_upgrader/api/>`_
and is built using `django-rest-framework <http://openwisp.io/docs/developer/hacking-openwisp-python-django.html#why-django-rest-framework>`_

For more information regarding Django REST Framework API views, please refer to the
`"Generic views" section in the Django REST Framework documentation <https://www.django-rest-framework.org/api-guide/generic-views/>`_.

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
