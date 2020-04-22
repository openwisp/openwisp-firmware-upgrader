openwisp-firmware-upgrader
==========================

.. image:: https://travis-ci.org/openwisp/openwisp-firmware-upgrader.svg
   :target: https://travis-ci.org/openwisp/openwisp-firmware-upgrader

.. image:: https://coveralls.io/repos/openwisp/openwisp-firmware-upgrader/badge.svg
  :target: https://coveralls.io/r/openwisp/openwisp-firmware-upgrader

.. image:: https://requires.io/github/openwisp/openwisp-firmware-upgrader/requirements.svg?branch=master
   :target: https://requires.io/github/openwisp/openwisp-firmware-upgrader/requirements/?branch=master
   :alt: Requirements Status

------------

OpenWISP 2 firmware upgrade module (Work in progress).

------------

.. contents:: **Table of Contents**:
   :backlinks: none
   :depth: 3

------------

Install Depdendencies
---------------------

Install spatialite and sqlite:

.. code-block:: shell

    sudo apt-get install sqlite3 libsqlite3-dev openssl libssl-dev
    sudo apt-get install gdal-bin libproj-dev libgeos-dev libspatialite-dev

Setup (integrate in an existing django project)
-----------------------------------------------

Follow the setup instructions of `openwisp-controller
<https://github.com/openwisp/openwisp-controller>`_, then add the settings described below.

.. code-block:: python

    INSTALLED_APPS = [
        # django apps
        # openwisp2 admin theme (must be loaded here)
        'openwisp_utils.admin_theme',
        # all-auth
        'django.contrib.sites',
        'allauth',
        'allauth.account',
        'django_extensions',
        'private_storage',
        # openwisp2 modules
        'openwisp_users',
        'openwisp_controller.pki',
        'openwisp_controller.config',
        'openwisp_controller.connection',
        'openwisp_controller.geo',
        'openwisp_firmware_upgrader',
        # admin
        'django.contrib.admin',
        'django.forms',
        # other dependencies
        'sortedm2m',
        'reversion',
        'leaflet',
        # rest framework
        'rest_framework',
        'rest_framework_gis',
        # channels
        'channels',
    ]

``urls.py``:

.. code-block:: python

    from django.conf import settings
    from django.contrib import admin
    from django.conf.urls import include, url
    from django.contrib.staticfiles.urls import staticfiles_urlpatterns

    urlpatterns = [
        url(r'^admin/', include(admin.site.urls)),
        url(r'', include('openwisp_controller.urls')),
        url('^firmware/', include('openwisp_firmware_upgrader.private_storage.urls')),
    ]

    urlpatterns += staticfiles_urlpatterns()

Add `apptemplates.Loader` to template loaders:

.. code-block:: python

    TEMPLATES = [
        {
            'BACKEND': 'django.template.backends.django.DjangoTemplates',
            'DIRS': [os.path.join(os.path.dirname(BASE_DIR), 'templates')],
            'OPTIONS': {
                'loaders': [
                    'apptemplates.Loader',
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

Configure caching (you may use a different cache storage if you want):

.. code-block:: python

    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': 'redis://localhost/0',
            'OPTIONS': {
                'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            }
        }
    }

    SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
    SESSION_CACHE_ALIAS = 'default'

Configure celery (you may use a different broker if you want):

.. code-block:: python

    # here we show how to configure celery with redis but you can
    # use other brokers if you want, consult the celery docs
    CELERY_BROKER_URL = 'redis://localhost/1'

    INSTALLED_APPS.append('djcelery_email')
    EMAIL_BACKEND = 'djcelery_email.backends.CeleryEmailBackend'

If you decide to use redis (as shown in these examples),
install the requierd python packages::

    pip install redis django-redis

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
| **default**: | ``300``      |
+--------------+--------------+

Timeout for the background tasks which perform firmware upgrades.

If for some unexpected reason an upgrade remains stuck for more than 5 minutes,
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

This setting can be used to add new image types for OpenWRT, eg:

.. code-block:: python

    OPENWISP_CUSTOM_OPENWRT_IMAGES = (
        ('customimage-squashfs-sysupgrade.bin', {
            'label': 'Custom WAP-1200',
            'boards': ('CWAP1200',)
        }),
    )

**Notes**:

- ``label`` it's the human readable name of the model which will be
  displayed in the UI
- ``boards`` is a tuple of board names with which the different versions
  of the hardware are identified on OpenWRT; this field is used to
  recognize automatically devices which have registered into OpenWISP

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

Installing for development
--------------------------

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

Extending openwisp-firmware-upgrader
------------------------------------

The ``tests/openwisp2/sample-firmware-upgrader`` may serve as an example for
extending *openwisp-firmware-upgrader* in your own application.

*openwisp-firmware-upgrader* provides a set of models and admin classes which can
be imported, extended and reused by third party apps.

To extend *openwisp-firmware-upgrader*, **you MUST NOT** add it to ``settings.INSTALLED_APPS``,
but you must create your own app (which goes into ``settings.INSTALLED_APPS``), import the
base classes from openwisp-firmware-upgrader and add your customizations.

In order to help django find the static files and templates of *openwisp-firmware-upgrader*,
you need to perform the steps described below.

1. Install ``openwisp-firmware-upgrader``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Install (and add to the requirement of your project) openwisp-firmware-upgrader::

    pip install openwisp-firmware-upgrader

2. Add ``EXTENDED_APPS``
~~~~~~~~~~~~~~~~~~~~~~~~

Add the following to your ``settings.py``:

.. code-block:: python

    EXTENDED_APPS = ('openwisp_firmware_upgrader',)

3. Add ``openwisp_utils.staticfiles.DependencyFinder``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Add ``openwisp_utils.staticfiles.DependencyFinder`` to
``STATICFILES_FINDERS`` in your ``settings.py``:

.. code-block:: python

    STATICFILES_FINDERS = [
        'django.contrib.staticfiles.finders.FileSystemFinder',
        'django.contrib.staticfiles.finders.AppDirectoriesFinder',
        'openwisp_utils.staticfiles.DependencyFinder',
    ]

4. Add ``openwisp_utils.loaders.DependencyLoader``
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

5. Add swapper configurations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Add the following to your ``settings.py``:

.. code-block:: python

    # Setting models for swapper module
    FIRMWARE_UPGRADER_CATEGORY_MODEL = 'YOUR_MODULE_NAME.Category'
    FIRMWARE_UPGRADER_BUILD_MODEL = 'YOUR_MODULE_NAME.Build'
    FIRMWARE_UPGRADER_FIRMWAREIMAGE_MODEL = 'YOUR_MODULE_NAME.FirmwareImage'
    FIRMWARE_UPGRADER_DEVICEFIRMWARE_MODEL = 'YOUR_MODULE_NAME.DeviceFirmware'
    FIRMWARE_UPGRADER_BATCHUPGRADEOPERATION_MODEL = 'YOUR_MODULE_NAME.BatchUpgradeOperation'
    FIRMWARE_UPGRADER_UPGRADEOPERATION_MODEL = 'YOUR_MODULE_NAME.UpgradeOperation'

Extending models
~~~~~~~~~~~~~~~~

For the purpose of showing an example, we added a simple "details" field to the
`models of the sample app in the test project <https://github.com/openwisp/openwisp-firmware-upgrader/tree/master/tests/openwisp2/sample_firmware_upgrader/models.py>`_.

You can add fields in a similar way in your ``models.py`` file.

Extending the admin
~~~~~~~~~~~~~~~~~~~

Please checkout the `admin.py file of the sample app <https://github.com/openwisp/openwisp-firmware-upgrader/tree/master/tests/openwisp2/sample_firmware_upgrader/admin.py>`_.

You can change ``CategoryAdmin``, ``BuildAdmin`` and
``BatchUpgradeOperationAdmin`` and these changes will be reflected in
your admin interface.

Reusing the base tests
~~~~~~~~~~~~~~~~~~~~~~

When developing a custom application based on this module, it's a good
idea to import and run the `base tests <https://github.com/openwisp/openwisp-firmware-upgrader/tree/master/openwisp_firmware_upgrader/tests/base>`_
too, so that you can be sure the changes you're introducing are not breaking
some of the existing features of openwisp-firmware-upgrader.

In case you need to add breaking changes, you can overwrite the tests defined
in the base classes to test your own behavior.

Contributing
------------

Please read the `OpenWISP contributing guidelines
<http://openwisp.io/docs/developer/contributing.html>`_
and also keep in mind the following:

1. Announce your intentions in the `OpenWISP Mailing List <https://groups.google.com/d/forum/openwisp>`_
2. Fork this repo and install it
3. Follow `PEP8, Style Guide for Python Code`_
4. Write code
5. Write tests for your code
6. Ensure all tests pass
7. Ensure test coverage does not decrease
8. Document your changes
9. Send pull request
