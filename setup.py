#!/usr/bin/env python
import os
import sys

from setuptools import find_packages, setup

from openwisp_firmware_upgrader import get_version

if sys.argv[-1] == 'publish':
    # delete any *.pyc, *.pyo and __pycache__
    os.system('find . | grep -E "(__pycache__|\.pyc|\.pyo$)" | xargs rm -rf')
    os.system("python setup.py sdist bdist_wheel")
    os.system("twine upload -s dist/*")
    os.system("rm -rf dist build")
    args = {'version': get_version()}
    print("You probably want to also tag the version now:")
    print("  git tag -a %(version)s -m 'version %(version)s'" % args)
    print("  git push --tags")
    sys.exit()


setup(
    name='openwisp-firmware-upgrader',
    version=get_version(),
    license='GPL3',
    author='Federico Capoano',
    author_email='federico.capoano@gmail.com',
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
        'openwisp-controller~=0.8',
        'openwisp-utils[rest]~=0.7.1',
        'django-private-storage~=2.2',
        'swapper~=1.1',
    ],
    classifiers=[
        'Development Status :: 3 - Alpha',
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
