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

Add ``apptemplates.Loader`` to template loaders:

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

One of the core values of the OpenWISP project is `Software Reusability <http://openwisp.io/docs/general/values.html#software-reusability-means-long-term-sustainability>`_,
for this reason *openwisp-firmware-upgrader* provides a set of base classes
which can be imported, extended and reused to create derivative apps.

In order to implement your custom version of *openwisp-firmware-upgrader*,
you need to perform the steps described in this section.

When in doubt, the code in the `test project <https://github.com/openwisp/openwisp-firmware-upgrader/tree/master/tests/openwisp2/>`_
and the `sample app <https://github.com/openwisp/openwisp-firmware-upgrader/tree/master/tests/openwisp2/sample_firmware_upgrader/>`_
will serve you as source of truth:
just replicate and adapt that code to get a basic derivative of
*openwisp-firmware-upgrader* working.

**Premise**: if you plan on using a customized version of this module,
we suggest to start with it since the beginning, because migrating your data
from the default module to your extended version may be time consuming.

1. Initialize your custom module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The first thing you need to do is to create a new django app which will
contain your custom version of *openwisp-firmware-upgrader*.

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
you're introducing are not breaking some of the existing features of *openwisp-firmware-upgrader*.

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

    url('^firmware/', include('openwisp_firmware_upgrader.private_storage.urls')),

Step 3: add an URL route pointing to your custom view in ``urls.py`` file:

.. code-block:: python

    # urls.py
    from myupgrader.views import FirmwareImageDownloadView

    urlpatterns = [
        # ... other URLs
        url(r'^(?P<path>.*)$', FirmwareImageDownloadView.as_view(), name='serve_private_file',),
    ]

Contributing
------------

Please refer to the `OpenWISP contributing guidelines <http://openwisp.io/docs/developer/contributing.html>`_.
