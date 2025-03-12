#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys

if __name__ == '__main__':
    sys.path.insert(0, 'tests')
    if os.environ.get('POSTGRESQL', False):
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'openwisp2.postgresql_settings')
    else:
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'openwisp2.settings')

    from django.core.management import execute_from_command_line

    args = sys.argv
    args.insert(1, 'test')
    if not os.environ.get('SAMPLE_APP', False):
        args.insert(2, 'openwisp_firmware_upgrader')
    else:
        args.insert(2, 'openwisp2')

    if os.environ.get('POSTGRESQL', False):
        args.extend(['--tag', 'selenium_tests'])
    else:
        args.extend(['--exclude-tag', 'selenium_tests'])

    execute_from_command_line(args)
