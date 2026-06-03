#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys

import pytest
from django.core.management import execute_from_command_line


def run_tests(extra_args, settings_module, test_app):
    """
    Run Django tests with the specified settings module via manage.py in-process.
    """
    args = [
        "./tests/manage.py",
        "test",
        test_app,
        "--settings",
        settings_module,
        "--pythonpath",
        "tests",
    ]
    args.extend(extra_args)
    execute_from_command_line(args)


if __name__ == "__main__":
    # Configure Django settings for test execution
    # (sets Celery to eager mode, configures in-memory channels layer, etc.)
    os.environ.setdefault("TESTING", "1")
    args = sys.argv.copy()[1:]
    exclude_pytest = "--exclude-pytest" in args
    if exclude_pytest:
        args.pop(args.index("--exclude-pytest"))
    # normal tests vs SAMPLE_APP
    if not os.environ.get("SAMPLE_APP", False):
        test_app = "openwisp_firmware_upgrader"
        app_dir = "openwisp_firmware_upgrader/"
    else:
        test_app = "openwisp2"
        app_dir = "tests/openwisp2/"
    # Run Django tests
    django_tests = run_tests(args, "openwisp2.settings", test_app)
    # Run pytest tests
    if not exclude_pytest:
        # Used to test django-channels
        sys.exit(pytest.main([app_dir]))
    else:
        sys.exit(django_tests)
