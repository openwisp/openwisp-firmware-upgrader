#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys

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
    args = sys.argv[1:]
    # normal tests vs SAMPLE_APP
    if not os.environ.get("SAMPLE_APP", False):
        test_app = "openwisp_firmware_upgrader"
    else:
        test_app = "openwisp2"
    # Run Django tests
    run_tests(args, "openwisp2.settings", test_app)
