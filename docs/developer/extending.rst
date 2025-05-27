Extending OpenWISP Firmware Upgrader
====================================

.. include:: ../partials/developer-docs.rst

One of the core values of the OpenWISP project is :ref:`Software
Reusability <values_software_reusability>`, for this reason *OpenWISP
Firmware Upgrader* provides a set of base classes which can be imported,
extended and reused to create derivative apps.

In order to implement your custom version of *OpenWISP Firmware Upgrader*,
you need to perform the steps described in this section.

When in doubt, the code in the `test project
<https://github.com/openwisp/openwisp-firmware-upgrader/tree/master/tests/openwisp2/>`_
and the `sample app
<https://github.com/openwisp/openwisp-firmware-upgrader/tree/master/tests/openwisp2/sample_firmware_upgrader/>`_
will serve you as source of truth: just replicate and adapt that code to
get a basic derivative of *OpenWISP Firmware Upgrader* working.

.. important::

    If you plan on using a customized version of this module, we suggest
    to start with it since the beginning, because migrating your data from
    the default module to your extended version may be time consuming.

.. contents:: **Table of Contents**:
    :depth: 2
    :local:

1. Initialize your Custom Module
--------------------------------

The first thing you need to do is to create a new django app which will
contain your custom version of *OpenWISP Firmware Upgrader*.

A django app is nothing more than a `python package
<https://docs.python.org/3/tutorial/modules.html#packages>`_ (a directory
of python scripts), in the following examples we'll call this django app
``myupgrader``, but you can name it how you want:

.. code-block::

    django-admin startapp myupgrader

Keep in mind that the command mentioned above must be called from a
directory which is available in your `PYTHON_PATH
<https://docs.python.org/3/using/cmdline.html#envvar-PYTHONPATH>`_ so that
you can then import the result into your project.

Now you need to add ``myupgrader`` to ``INSTALLED_APPS`` in your
``settings.py``, ensuring also that ``openwisp_firmware_upgrader`` has
been removed:

.. code-block:: python

    INSTALLED_APPS = [
        # ... other apps ...
        # 'openwisp_firmware_upgrader'  <-- comment out or delete this line
        "myupgrader"
    ]

For more information about how to work with django projects and django
apps, please refer to the `django documentation
<https://docs.djangoproject.com/en/4.2/intro/tutorial01/>`_.

2. Install ``openwisp-firmware-upgrader``
-----------------------------------------

Install (and add to the requirement of your project)
``openwisp-firmware-upgrader``:

.. code-block::

    pip install openwisp-firmware-upgrader

3. Add ``EXTENDED_APPS``
------------------------

Add the following to your ``settings.py``:

.. code-block:: python

    EXTENDED_APPS = ["openwisp_firmware_upgrader"]

4. Add ``openwisp_utils.staticfiles.DependencyFinder``
------------------------------------------------------

Add ``openwisp_utils.staticfiles.DependencyFinder`` to
``STATICFILES_FINDERS`` in your ``settings.py``:

.. code-block:: python

    STATICFILES_FINDERS = [
        "django.contrib.staticfiles.finders.FileSystemFinder",
        "django.contrib.staticfiles.finders.AppDirectoriesFinder",
        "openwisp_utils.staticfiles.DependencyFinder",
    ]

5. Add ``openwisp_utils.loaders.DependencyLoader``
--------------------------------------------------

Add ``openwisp_utils.loaders.DependencyLoader`` to ``TEMPLATES`` in your
``settings.py``:

.. code-block:: python

    TEMPLATES = [
        {
            "BACKEND": "django.template.backends.django.DjangoTemplates",
            "OPTIONS": {
                "loaders": [
                    "django.template.loaders.filesystem.Loader",
                    "django.template.loaders.app_directories.Loader",
                    "openwisp_utils.loaders.DependencyLoader",
                ],
                "context_processors": [
                    "django.template.context_processors.debug",
                    "django.template.context_processors.request",
                    "django.contrib.auth.context_processors.auth",
                    "django.contrib.messages.context_processors.messages",
                ],
            },
        }
    ]

6. Inherit the AppConfig Class
------------------------------

Please refer to the following files in the sample app of the test project:

- `sample_firmware_upgrader/__init__.py
  <https://github.com/openwisp/openwisp-firmware-upgrader/tree/master/tests/openwisp2/sample_firmware_upgrader/__init__.py>`_.
- `sample_firmware_upgrader/apps.py
  <https://github.com/openwisp/openwisp-firmware-upgrader/tree/master/tests/openwisp2/sample_firmware_upgrader/apps.py>`_.

You have to replicate and adapt that code in your project.

For more information regarding the concept of ``AppConfig`` please refer
to the `"Applications" section in the django documentation
<https://docs.djangoproject.com/en/4.2/ref/applications/>`_.

7. Create your Custom Models
----------------------------

For the purpose of showing an example, we added a simple "details" field
to the `models of the sample app in the test project
<https://github.com/openwisp/openwisp-firmware-upgrader/tree/master/tests/openwisp2/sample_firmware_upgrader/models.py>`_.

You can add fields in a similar way in your ``models.py`` file.

.. note::

    If you have questions about using, extending, or developing models,
    refer to the `"Models" section of the Django documentation
    <https://docs.djangoproject.com/en/4.2/topics/db/models/>`_.

8. Add Swapper Configurations
-----------------------------

Once you have created the models, add the following to your
``settings.py``:

.. code-block:: python

    # Setting models for swapper module
    FIRMWARE_UPGRADER_CATEGORY_MODEL = "myupgrader.Category"
    FIRMWARE_UPGRADER_BUILD_MODEL = "myupgrader.Build"
    FIRMWARE_UPGRADER_FIRMWAREIMAGE_MODEL = "myupgrader.FirmwareImage"
    FIRMWARE_UPGRADER_DEVICEFIRMWARE_MODEL = "myupgrader.DeviceFirmware"
    FIRMWARE_UPGRADER_BATCHUPGRADEOPERATION_MODEL = "myupgrader.BatchUpgradeOperation"
    FIRMWARE_UPGRADER_UPGRADEOPERATION_MODEL = "myupgrader.UpgradeOperation"

Substitute ``myupgrader`` with the name you chose in step 1.

9. Create Database Migrations
-----------------------------

Create and apply database migrations:

.. code-block:: shell

    ./manage.py makemigrations
    ./manage.py migrate

For more information, refer to the `"Migrations" section in the django
documentation
<https://docs.djangoproject.com/en/4.2/topics/migrations/>`_.

10. Create the Admin
--------------------

Refer to the `admin.py file of the sample app
<https://github.com/openwisp/openwisp-firmware-upgrader/tree/master/tests/openwisp2/sample_firmware_upgrader/admin.py>`_.

To introduce changes to the admin, you can do it in two main ways which
are described below.

For more information regarding how the django admin works, or how it can
be customized, please refer to `"The django admin site" section in the
django documentation
<https://docs.djangoproject.com/en/4.2/ref/contrib/admin/>`_.

1. Monkey Patching
~~~~~~~~~~~~~~~~~~

If the changes you need to add are relatively small, you can resort to
monkey patching.

For example:

.. code-block:: python

    from openwisp_firmware_upgrader.admin import (
        BatchUpgradeOperationAdmin,
        BuildAdmin,
        CategoryAdmin,
    )

    BuildAdmin.list_display.insert(1, "my_custom_field")
    BuildAdmin.ordering = ["-my_custom_field"]

2. Inheriting Admin Classes
~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you need to introduce significant changes and/or you don't want to
resort to monkey patching, you can proceed as follows:

.. code-block:: python

    from django.contrib import admin
    from openwisp_firmware_upgrader.admin import (
        BatchUpgradeOperationAdmin as BaseBatchUpgradeOperationAdmin,
        BuildAdmin as BaseBuildAdmin,
        CategoryAdmin as BaseCategoryAdmin,
    )
    from openwisp_firmware_upgrader.swapper import load_model

    BatchUpgradeOperation = load_model("BatchUpgradeOperation")
    Build = load_model("Build")
    Category = load_model("Category")
    DeviceFirmware = load_model("DeviceFirmware")
    FirmwareImage = load_model("FirmwareImage")
    UpgradeOperation = load_model("UpgradeOperation")

    admin.site.unregister(BatchUpgradeOperation)
    admin.site.unregister(Build)
    admin.site.unregister(Category)


    class BatchUpgradeOperationAdmin(BaseBatchUpgradeOperationAdmin):
        # add your changes here
        pass


    class BuildAdmin(BaseBuildAdmin):
        # add your changes here
        pass


    class CategoryAdmin(BaseCategoryAdmin):
        # add your changes here
        pass

11. Create Root URL Configuration
---------------------------------

Please refer to the `urls.py
<https://github.com/openwisp/openwisp-firmware-upgrader/tree/master/tests/openwisp2/urls.py>`_
file in the test project.

For more information about URL configuration in django, please refer to
the `"URL dispatcher" section in the django documentation
<https://docs.djangoproject.com/en/4.2/topics/http/urls/>`_.

12. Create ``celery.py``
------------------------

Please refer to the `celery.py
<https://github.com/openwisp/openwisp-firmware-upgrader/tree/master/tests/openwisp2/celery.py>`_
file in the test project.

For more information about the usage of celery in django, please refer to
the `"First steps with Django" section in the celery documentation
<https://docs.celeryproject.org/en/master/django/first-steps-with-django.html>`_.

13. Import the Automated Tests
------------------------------

When developing a custom application based on this module, it's a good
idea to import and run the base tests too, so that you can be sure the
changes you're introducing are not breaking some of the existing features
of *OpenWISP Firmware Upgrader*.

In case you need to add breaking changes, you can overwrite the tests
defined in the base classes to test your own behavior.

See the `tests of the sample app
<https://github.com/openwisp/openwisp-firmware-upgrader/blob/master/tests/openwisp2/sample_firmware_upgrader/tests.py>`_
to find out how to do this.

You can then run tests with:

.. code-block::

    # the --parallel flag is optional
    ./manage.py test --parallel myupgrader

Substitute ``myupgrader`` with the name you chose in step 1.

For more information about automated tests in django, please refer to
`"Testing in Django"
<https://docs.djangoproject.com/en/4.2/topics/testing/>`_.

Other Base Classes That Can be Inherited and Extended
-----------------------------------------------------

The following steps are not required and are intended for more advanced
customization.

.. _firmware_upgrader_image_download_view:

``FirmwareImageDownloadView``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This view controls how the firmware images are stored and who has
permission to download them.

The full python path is:
``openwisp_firmware_upgrader.private_storage.FirmwareImageDownloadView``.

If you want to extend this view, you will have to perform the additional
steps below.

Step 1. import and extend view:

.. code-block:: python

    # myupgrader/views.py
    from openwisp_firmware_upgrader.private_storage import (
        FirmwareImageDownloadView as BaseFirmwareImageDownloadView,
    )


    class FirmwareImageDownloadView(BaseFirmwareImageDownloadView):
        # add your customizations here ...
        pass

Step 2: remove the following line from your root ``urls.py`` file:

.. code-block:: python

    path(
        "firmware/",
        include("openwisp_firmware_upgrader.private_storage.urls"),
    ),

Step 3: add an URL route pointing to your custom view in ``urls.py`` file:

.. code-block:: python

    # urls.py
    from myupgrader.views import FirmwareImageDownloadView

    urlpatterns = [
        # ... other URLs
        path(
            "<your-custom-path>",
            FirmwareImageDownloadView.as_view(),
            name="serve_private_file",
        ),
    ]

For more information regarding django views, please refer to the `"Class
based views" section in the django documentation
<https://docs.djangoproject.com/en/4.2/topics/class-based-views/>`_.

API Views
---------

If you need to customize the behavior of the API views, the procedure to
follow is similar to the one described in :ref:`FirmwareImageDownloadView
<firmware_upgrader_image_download_view>`, with the difference that you may
also want to create your own `serializers
<https://www.django-rest-framework.org/api-guide/serializers/>`_ if
needed.

The API code is stored in `openwisp_firmware_upgrader.api
<https://github.com/openwisp/openwisp-firmware-upgrader/blob/master/openwisp_firmware_upgrader/api/>`_
and is built using `django-rest-framework
<http://openwisp.io/docs/developer/hacking-openwisp-python-django.html#why-django-rest-framework>`_

For more information regarding Django REST Framework API views, please
refer to the `"Generic views" section in the Django REST Framework
documentation
<https://www.django-rest-framework.org/api-guide/generic-views/>`_.
