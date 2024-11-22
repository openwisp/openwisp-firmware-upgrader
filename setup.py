#!/usr/bin/env python
from setuptools import find_packages, setup

from openwisp_firmware_upgrader import get_version

setup(
    name='openwisp-firmware-upgrader',
    version=get_version(),
    license='GPL3',
    author='OpenWISP',
    author_email='support@openwisp.io',
    description='Firmware upgrader module of OpenWISP',
    long_description=open('README.rst').read(),
    url='http://openwisp.org',
    download_url='https://github.com/openwisp/openwisp-firmware-upgrader/releases',
    platforms=['Platform Independent'],
    keywords=['django', 'netjson', 'networking', 'openwisp', 'firmware'],
    packages=find_packages(exclude=['tests*', 'docs*']),
    include_package_data=True,
    zip_safe=False,
    install_requires=[
        'openwisp-controller~=1.1.0',
        'django-private-storage~=3.1.0',
    ],
    classifiers=[
        'Development Status :: 5 - Production/Stable ',
        'Environment :: Web Environment',
        'Topic :: Internet :: WWW/HTTP',
        'Topic :: System :: Networking',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'Operating System :: OS Independent',
        'Framework :: Django',
        'Programming Language :: Python :: 3',
    ],
)
