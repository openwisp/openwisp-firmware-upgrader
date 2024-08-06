REST API Reference
==================

.. contents:: **Table of contents**:
    :depth: 1
    :local:

.. _firmware_upgrader_live_documentation:

Live Documentation
------------------

.. image:: https://raw.githubusercontent.com/openwisp/openwisp-firmware-upgrader/docs/docs/images/api-docs.png
    :target: https://raw.githubusercontent.com/openwisp/openwisp-firmware-upgrader/docs/docs/images/api-docs.png

A general live API documentation (following the OpenAPI specification) at
``/api/v1/docs/``.

.. _firmware_upgrader_browsable_web_interface:

Browsable Web Interface
-----------------------

.. image:: https://raw.githubusercontent.com/openwisp/openwisp-firmware-upgrader/docs/docs/images/api-ui.png
    :target: https://raw.githubusercontent.com/openwisp/openwisp-firmware-upgrader/docs/docs/images/api-ui.png

Additionally, opening any of the endpoints :ref:`listed below
<firmware_upgrader_list_endpoints>` directly in the browser will show the
`browsable API interface of Django-REST-Framework
<https://www.django-rest-framework.org/topics/browsable-api/>`_, which
makes it even easier to find out the details of each endpoint.

Authentication
--------------

See openwisp-users: :ref:`authenticating with the user token
<authenticating_rest_api>`.

When browsing the API via the :ref:`firmware_upgrader_live_documentation`
or the :ref:`firmware_upgrader_browsable_web_interface`, you can also use
the session authentication by logging in the django admin.

Pagination
----------

All *list* endpoints support the ``page_size`` parameter that allows
paginating the results in conjunction with the ``page`` parameter.

.. code-block:: text

    GET /api/v1/firmware-upgrader/build/?page_size=10
    GET /api/v1/firmware-upgrader/build/?page_size=10&page=2

Filtering by Organization Slug
------------------------------

Most endpoints allow to filter by organization slug, e.g.:

.. code-block:: text

    GET /api/v1/firmware-upgrader/build/?organization=org-slug

.. _firmware_upgrader_list_endpoints:

List of Endpoints
-----------------

Since the detailed explanation is contained in the
:ref:`firmware_upgrader_live_documentation` and in the
:ref:`firmware_upgrader_browsable_web_interface` of each point, here we'll
provide just a list of the available endpoints, for further information
please open the URL of the endpoint in your browser.

List Mass Upgrade Operations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

    GET /api/v1/firmware-upgrader/batch-upgrade-operation/

**Available filters**

The list of batch upgrade operations provides the following filters:

- ``build`` (Firmware build ID)
- ``status`` (One of: idle, in-progress, success, failed)

Here's a few examples:

.. code-block:: text

    GET /api/v1/firmware-upgrader/batch-upgrade-operation/?build={build_id}
    GET /api/v1/firmware-upgrader/batch-upgrade-operation/?status={status}

Get Mass Upgrade Operation Detail
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

    GET /api/v1/firmware-upgrader/batch-upgrade-operation/{id}/

List Firmware Builds
~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

    GET /api/v1/firmware-upgrader/build/

**Available filters**

The list of firmware builds provides the following filters:

- ``category`` (Firmware category ID)
- ``version`` (Firmware build version)
- ``os`` (Firmware build os identifier)

Here's a few examples:

.. code-block:: text

    GET /api/v1/firmware-upgrader/build/?category={category_id}
    GET /api/v1/firmware-upgrader/build/?version={version}
    GET /api/v1/firmware-upgrader/build/?os={os}

Create Firmware Build
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

    POST /api/v1/firmware-upgrader/build/

Get Firmware Build Details
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

    GET /api/v1/firmware-upgrader/build/{id}/

Change Details of Firmware Build
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

    PUT /api/v1/firmware-upgrader/build/{id}/

Patch Details of Firmware Build
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

    PATCH /api/v1/firmware-upgrader/build/{id}/

Delete Firmware Build
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

    DELETE /api/v1/firmware-upgrader/build/{id}/

Get List of Images of a Firmware Build
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

    GET /api/v1/firmware-upgrader/build/{id}/image/

**Available filters**

The list of images of a firmware build can be filtered by using ``type``
(any one of the available firmware image types).

.. code-block:: text

    GET /api/v1/firmware-upgrader/build/{id}/image/?type={type}

Upload New Firmware Image to the Build
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

    POST /api/v1/firmware-upgrader/build/{id}/image/

Get Firmware Image Details
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

    GET /api/v1/firmware-upgrader/build/{build_id}/image/{id}/

Delete Firmware Image
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

    DELETE /api/v1/firmware-upgrader/build/{build_id}/image/{id}/

Download Firmware Image
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

    GET /api/v1/firmware-upgrader/build/{build_id}/image/{id}/download/

Perform Batch Upgrade
~~~~~~~~~~~~~~~~~~~~~

Upgrades all the devices related to the specified build ID.

.. code-block:: text

    POST /api/v1/firmware-upgrader/build/{id}/upgrade/

Dry-run Batch Upgrade
~~~~~~~~~~~~~~~~~~~~~

Returns a list representing the ``DeviceFirmware`` and ``Device``
instances that would be upgraded if POST is used.

``Device`` objects are indicated only when no ``DeviceFirmware`` object
exists for a device which would be upgraded.

.. code-block:: text

    GET /api/v1/firmware-upgrader/build/{id}/upgrade/

List Firmware Categories
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

    GET /api/v1/firmware-upgrader/category/

Create New Firmware Category
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

    POST /api/v1/firmware-upgrader/category/

Get Firmware Category Details
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

    GET /api/v1/firmware-upgrader/category/{id}/

Change the Details of a Firmware Category
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

    PUT /api/v1/firmware-upgrader/category/{id}/

Patch the Details of a Firmware Category
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

    PATCH /api/v1/firmware-upgrader/category/{id}/

Delete a Firmware Category
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

    DELETE /api/v1/firmware-upgrader/category/{id}/

List Upgrade Operations
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

    GET /api/v1/firmware-upgrader/upgrade-operation/

**Available filters**

The list of upgrade operations provides the following filters:

- ``device__organization`` (Organization ID of the device)
- ``device__organization_slug`` (Organization slug of the device)
- ``device`` (Device ID)
- ``image`` (Firmware image ID)
- ``status`` (One of: in-progress, success, failed, aborted)

Here's a few examples:

.. code-block:: text

    GET /api/v1/firmware-upgrader/upgrade-operation/?device__organization={organization_id}
    GET /api/v1/firmware-upgrader/upgrade-operation/?device__organization__slug={organization_slug}
    GET /api/v1/firmware-upgrader/upgrade-operation/?device={device_id}
    GET /api/v1/firmware-upgrader/upgrade-operation/?image={image_id}
    GET /api/v1/firmware-upgrader/upgrade-operation/?status={status}

Get Upgrade Operation Details
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

    GET /api/v1/firmware-upgrader/upgrade-operation/{id}

List Device Upgrade Operations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

    GET /api/v1/firmware-upgrader/device/{device_id}/upgrade-operation/

**Available filters**

The list of device upgrade operations can be filtered by ``status`` (one
of: in-progress, success, failed, aborted).

.. code-block:: text

    GET /api/v1/firmware-upgrader/device/{device_id}/upgrade-operation/?status={status}

Create Device Firmware
~~~~~~~~~~~~~~~~~~~~~~

Sending a PUT request to the endpoint below will create a new device
firmware if it does not already exist.

.. code-block:: text

    PUT /api/v1/firmware-upgrader/device/{device_id}/firmware/

Get Device Firmware Details
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

    GET /api/v1/firmware-upgrader/device/{device_id}/firmware/

Change Details of Device Firmware
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

    PUT /api/v1/firmware-upgrader/device/{device_id}/firmware/

Patch Details of Device Firmware
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

    PATCH /api/v1/firmware-upgrader/device/{device_id}/firmware/

Delete Device Firmware
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

    DELETE /api/v1/firmware-upgrader/device/{device_pk}/firmware/
