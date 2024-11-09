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
    sudo apt-get install gdal-bin libproj-dev libgeos-dev libspatialite-dev

Installing for Development
--------------------------

Create project directory:

.. code-block:: shell

    mkdir openwisp && cd openwisp

The directory structure will look like this:

.. code-block:: text

    openwisp/                         # Main project folder
    ├── env/                          # Virtual environment 
    └── openwisp-firmware-upgrader/   # Cloned repository

Fork and clone the forked repository:

.. code-block:: shell

    git clone git://github.com/<your_fork>/openwisp-firmware-upgrader

Navigate into the cloned repository:

.. code-block:: shell

    cd openwisp-firmware-upgrader/

Setup and activate a virtual-environment (we'll be using `virtualenv
<https://pypi.org/project/virtualenv/>`_):

.. code-block:: shell

    python -m virtualenv ../env
    source ../env/bin/activate

Make sure that your base python packages are up to date before moving to
the next step:

.. code-block:: shell

    pip install -U pip wheel setuptools

Install test requirements:

.. code-block:: shell

    pip install -r requirements-test.txt

Launch Redis:

.. code-block:: shell

    docker-compose up -d redis

Install development dependencies:

.. code-block:: shell

    pip install -e .
    pip install -r requirements-test.txt
    sudo npm install -g jshint stylelint

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

Run tests with:

.. code-block:: shell

    # run qa checks
    ./run-qa-checks

    # standard tests
    ./runtests.py

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
