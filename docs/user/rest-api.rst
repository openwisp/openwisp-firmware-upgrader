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

**Available filters**

The list of batch upgrade operations provides the following filters:

- ``build`` (Firmware build ID)
- ``status`` (One of: idle, in-progress, success, failed)

Here's a few examples:

.. code-block:: text

    GET /api/v1/firmware-upgrader/batch-upgrade-operation/?build={build_id}
    GET /api/v1/firmware-upgrader/batch-upgrade-operation/?status={status}

Get mass upgrade operation detail
#################################

.. code-block:: text

    GET /api/v1/firmware-upgrader/batch-upgrade-operation/{id}/

List firmware builds
####################

.. code-block:: text

    GET /api/v1/firmware-upgrader/build/

**Available filters**

The list of firmware builds provides the following filters:

- ``category`` (Firmware category ID)
- ``version``  (Firmware build version)
- ``os`` (Firmware build os identifier)

Here's a few examples:

.. code-block:: text

    GET /api/v1/firmware-upgrader/build/?category={category_id}
    GET /api/v1/firmware-upgrader/build/?version={version}
    GET /api/v1/firmware-upgrader/build/?os={os}

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

**Available filters**

The list of images of a firmware build can be filtered by using
``type`` (any one of the available firmware image types).

.. code-block:: text

    GET /api/v1/firmware-upgrader/build/{id}/image/?type={type}

Upload new firmware image to the build
######################################

.. code-block:: text

    POST /api/v1/firmware-upgrader/build/{id}/image/

Get firmware image details
##########################

.. code-block:: text

    GET /api/v1/firmware-upgrader/build/{build_id}/image/{id}/

Delete firmware image
#####################

.. code-block:: text

    DELETE /api/v1/firmware-upgrader/build/{build_id}/image/{id}/

Download firmware image
#######################

.. code-block:: text

    GET /api/v1/firmware-upgrader/build/{build_id}/image/{id}/download/

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

List upgrade operations
#######################

.. code-block:: text

    GET /api/v1/firmware-upgrader/upgrade-operation/

**Available filters**

The list of upgrade operations provides the following filters:

- ``device__organization`` (Organization ID of the device)
- ``device__organization_slug``  (Organization slug of the device)
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

Get upgrade operation details
#############################

.. code-block:: text

    GET /api/v1/firmware-upgrader/upgrade-operation/{id}

List device upgrade operations
##############################

.. code-block:: text

    GET /api/v1/firmware-upgrader/device/{device_id}/upgrade-operation/

**Available filters**

The list of device upgrade operations can be filtered by
``status`` (one of: in-progress, success, failed, aborted).

.. code-block:: text

    GET /api/v1/firmware-upgrader/device/{device_id}/upgrade-operation/?status={status}

Create device firmware
######################

Sending a PUT request to the endpoint below will
create a new device firmware if it does not already exist.

.. code-block:: text

    PUT /api/v1/firmware-upgrader/device/{device_id}/firmware/

Get device firmware details
###########################

.. code-block:: text

    GET /api/v1/firmware-upgrader/device/{device_id}/firmware/

Change details of device firmware
#################################

.. code-block:: text

    PUT /api/v1/firmware-upgrader/device/{device_id}/firmware/

Patch details of device firmware
#################################

.. code-block:: text

    PATCH /api/v1/firmware-upgrader/device/{device_id}/firmware/

Delete device firmware
######################

.. code-block:: text

    DELETE /api/v1/firmware-upgrader/device/{device_pk}/firmware/
