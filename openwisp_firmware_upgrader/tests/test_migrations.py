from unittest import mock

from django.apps import apps
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from ..hardware import OPENWRT_FIRMWARE_IMAGE_MAP

_MULTI_BOARD_TYPE = "ar71xx-generic-cpe210-220-v1-squashfs-sysupgrade.bin"
_MOCK_NOTIFY = "openwisp_notifications.signals.notify.send"
_MOCK_EXTRACT_DELAY = "openwisp_firmware_upgrader.tasks.extract_firmware_metadata.delay"


class TestMultiBoardReconciliationMigration(TransactionTestCase):
    app_label = "firmware_upgrader"
    migrate_from = "0017_alter_batchupgradeoperation_status"
    migrate_to = "0023_backfill_board_from_hardware_map"
    migrate_to_dependency = "0022_alter_firmwareimage_compatible"

    def setUp(self):
        boards = OPENWRT_FIRMWARE_IMAGE_MAP[_MULTI_BOARD_TYPE]["boards"]
        assert len(boards) > 1, "fixture type must map to multiple boards"

        executor = MigrationExecutor(connection)
        self.addCleanup(call_command, "migrate", self.app_label, verbosity=0)
        executor.migrate([(self.app_label, self.migrate_from)])

        old_apps = executor.loader.project_state(
            (self.app_label, self.migrate_from)
        ).apps
        Organization = old_apps.get_model("openwisp_users", "Organization")
        Category = old_apps.get_model(self.app_label, "Category")
        Build = old_apps.get_model(self.app_label, "Build")
        FirmwareImage = old_apps.get_model(self.app_label, "FirmwareImage")

        org = Organization.objects.create(name="test-org", slug="test-org")
        category = Category.objects.create(name="Test Category", organization=org)
        build = Build.objects.create(category=category, version="0.1")
        self.image_pk = FirmwareImage.objects.create(
            build=build,
            type=_MULTI_BOARD_TYPE,
            file="firmware/fake-legacy-image.bin",
        ).pk
        self.assertFalse(hasattr(FirmwareImage(), "extraction_status"))

    def tearDown(self):
        call_command("migrate", self.app_label, verbosity=0)
        super().tearDown()

    def test_legacy_multi_board_image_is_reconciled(self):
        with mock.patch(_MOCK_EXTRACT_DELAY) as mock_delay, mock.patch(
            _MOCK_NOTIFY
        ) as mock_notify:
            call_command("migrate", self.app_label, self.migrate_to, verbosity=0)

            FirmwareImage = apps.get_model(self.app_label, "FirmwareImage")
            image = FirmwareImage.objects.get(pk=self.image_pk)

            with self.subTest("final status is failed"):
                self.assertEqual(image.extraction_status, "failed")

            with self.subTest("reconciliation log is retained"):
                self.assertIn("compatible with multiple boards", image.extraction_log)

            with self.subTest("image is not queued for extraction"):
                queued_pks = {str(call.args[0]) for call in mock_delay.call_args_list}
                self.assertNotIn(str(image.pk), queued_pks)

            with self.subTest("notification eligibility"):
                mock_notify.assert_called()
                call_kwargs = mock_notify.call_args.kwargs
                self.assertEqual(call_kwargs["level"], "warning")
                self.assertIn("multiple boards", str(call_kwargs["message"]))

            with self.subTest("build status reflects the failed image"):
                self.assertEqual(
                    image.build.status,
                    "failed",
                    "build status was not recomputed after reconciliation",
                )

    def test_legacy_multi_board_image_reconciliation_is_idempotent(self):
        with mock.patch(_MOCK_EXTRACT_DELAY), mock.patch(_MOCK_NOTIFY):
            call_command("migrate", self.app_label, self.migrate_to, verbosity=0)
            FirmwareImage = apps.get_model(self.app_label, "FirmwareImage")
            image = FirmwareImage.objects.get(pk=self.image_pk)
            first_log = image.extraction_log
            self.assertEqual(first_log.count("compatible with multiple boards"), 1)
            call_command(
                "migrate", self.app_label, self.migrate_to_dependency, verbosity=0
            )
            call_command("migrate", self.app_label, self.migrate_to, verbosity=0)
            image.refresh_from_db()
            self.assertEqual(
                image.extraction_log.count("compatible with multiple boards"), 1
            )
            self.assertEqual(image.extraction_log, first_log)
