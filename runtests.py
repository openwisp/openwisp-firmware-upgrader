#!/usr/bin/env python

"""Run firmware tests and validate focused Django test labels."""

import os
import sys

import pytest
from django.core.management import execute_from_command_line

from openwisp_utils.test.runner import (
    InvalidTestArgument,
    compile_test_label_pattern,
    parse_test_arguments,
    validate_test_labels,
)


def run_focused_tests(arguments):
    import django

    sample_modules = (
        "openwisp2.sample_firmware_upgrader.tests",
        "openwisp2.sample_connection.tests",
    )
    pattern = compile_test_label_pattern(
        module_roots=("openwisp_firmware_upgrader.tests",),
        exact_modules=sample_modules,
        allow_subpackages=True,
    )
    try:
        labels, flags = parse_test_arguments(
            arguments, pattern, ("--failfast", "--noinput"), require_label=True
        )
        sample_labels = [
            label for label in labels if label.group("module") in sample_modules
        ]
        if sample_labels and len(sample_labels) != len(labels):
            raise InvalidTestArgument(
                "Unsupported test argument: run sample app tests separately"
            )
        if sample_labels:
            os.environ["SAMPLE_APP"] = "1"
        os.environ["TESTING"] = "1"
        os.environ["DJANGO_SETTINGS_MODULE"] = "openwisp2.settings"
        sys.path.insert(0, "tests")
        sys.argv[1:] = ["test", *(label.group(0) for label in labels), *flags]
        django.setup()
        validate_test_labels(labels)
    except InvalidTestArgument as error:
        print(error, file=sys.stderr)
        return 2
    execute_from_command_line(sys.argv)
    return 0


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
    if sys.argv[1:2] == ["--focused"]:
        sys.exit(run_focused_tests(sys.argv[2:]))

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
    # Run pytest tests (only when testing extensions and if not explicltly excluded)
    if os.environ.get("SAMPLE_APP", False) and not exclude_pytest:
        # Used to test django-channels
        sys.exit(pytest.main([app_dir]))
    sys.exit(django_tests)
