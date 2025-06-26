Developer Installation Instructions
===================================

.. include:: ../partials/developer-docs.rst

.. contents:: **Table of contents**:
    :depth: 2
    :local:

Requirements
------------

- Python >= 3.8
- :doc:`OpenWISP Controller (and its dependencies)
  </controller/developer/installation>` >= 1.0.0

Install Dependencies
--------------------

Install spatialite and sqlite:

.. code-block:: shell

    sudo apt-get install sqlite3 libsqlite3-dev openssl libssl-dev
    sudo apt-get install gdal-bin libproj-dev libgeos-dev libspatialite-dev libsqlite3-mod-spatialite

Installing for Development
--------------------------

Fork and clone the forked repository:

.. code-block:: shell

    git clone git://github.com/<your_fork>/openwisp-firmware-upgrader

Navigate into the cloned repository:

.. code-block:: shell

    cd openwisp-firmware-upgrader/

.. _firmware_upgrader_dev_docker:

Launch Redis and PostgreSQL:

.. code-block:: shell

    docker compose up -d redis postgres

Setup and activate a virtual-environment (we'll be using `virtualenv
<https://pypi.org/project/virtualenv/>`_):

.. code-block:: shell

    python -m virtualenv env
    source env/bin/activate

Make sure that your base python packages are up to date before moving to
the next step:

.. code-block:: shell

    pip install -U pip wheel setuptools

Install development dependencies:

.. code-block:: shell

    pip install -e .
    pip install -r requirements-test.txt
    sudo npm install -g prettier

Install WebDriver for Chromium for your browser version from
https://chromedriver.chromium.org/home and Extract ``chromedriver`` to one
of directories from your ``$PATH`` (example: ``~/.local/bin/``).

Create database:

.. code-block:: shell

    cd tests/
    ./manage.py migrate
    ./manage.py createsuperuser

Launch development server:

.. code-block:: shell

    ./manage.py runserver 0.0.0.0:8000

You can access the admin interface at ``http://127.0.0.1:8000/admin/``.

Run celery and celery-beat with the following commands (separate terminal
windows are needed):

.. code-block:: shell

    # (cd tests)
    celery -A openwisp2 worker -l info
    celery -A openwisp2 beat -l info

Run quality assurance tests with:

.. code-block:: shell

    ./run-qa-checks

Run tests with (make sure you have the :ref:`selenium dependencies
<selenium_dependencies>` installed locally first):

.. code-block:: shell

    # standard tests
    ./runtests.py

Some tests, such as the Selenium UI tests, require a PostgreSQL database
to run. If you don't have a PostgreSQL database running on your system,
you can use the :ref:`Docker Compose configuration provided in this
repository <firmware_upgrader_dev_docker>`. Once set up, you can run these
specific tests as follows:

.. code-block:: shell

    # Run only specific selenium tests classes
    cd tests/
    DJANGO_SETTINGS_MODULE=openwisp2.postgresql_settings ./manage.py test openwisp_firmware_upgrader.tests.test_selenium.TestDeviceAdmin

    # tests for the sample app
    SAMPLE_APP=1 ./runtests.py --keepdb --failfast

When running the last line of the previous example, the environment
variable ``SAMPLE_APP`` activates the app in
``/tests/openwisp2/sample_firmware_upgrader/`` which is a simple django
app that extends ``openwisp-firmware-upgrader`` with the sole purpose of
testing its extensibility, for more information regarding this concept,
read :doc:`extending`.

.. important::

    If you want to add ``openwisp-firmware-upgrader`` to an existing
    Django project, then you can take reference from the `test project in
    openwisp-firmware-upgrader repository
    <https://github.com/openwisp/openwisp-firmware-upgrader/tree/master/tests/openwisp2>`_
