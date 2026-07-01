from datetime import timedelta
from unittest import mock

from django.test import TransactionTestCase
from django.utils import timezone

from .. import settings as app_settings
from .. import tasks
from ..exceptions import ReconnectionFailed
from ..swapper import load_model
from .base import TestUpgraderMixin

UpgradeOperation = load_model("UpgradeOperation")
BatchUpgradeOperation = load_model("BatchUpgradeOperation")


class TestPendingUpgradeReminders(TestUpgraderMixin, TransactionTestCase):
    def _create_persistent_batch(self, build=None):
        if build is None:
            build = self._create_build()
        return BatchUpgradeOperation.objects.create(
            build=build, status="in-progress", is_persistent=True
        )

    def _create_pending_op_for_batch(self, batch, device_fw=None):
        if device_fw is None:
            device_fw = self._create_device_firmware()
        return UpgradeOperation.objects.create(
            device=device_fw.device,
            image=device_fw.image,
            batch=batch,
            status="pending",
            is_persistent=True,
        )

    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_no_pending_batches_no_notification(self, mocked_notify):
        batch = self._create_persistent_batch()
        device_fw = self._create_device_firmware()
        UpgradeOperation.objects.create(
            device=device_fw.device,
            image=device_fw.image,
            batch=batch,
            status="success",
            is_persistent=True,
        )
        tasks.send_pending_upgrade_reminders.run()
        mocked_notify.assert_not_called()

    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_qualifying_batch_fires_reminder(self, mocked_notify):
        batch = self._create_persistent_batch()
        self._create_pending_op_for_batch(batch)
        BatchUpgradeOperation.objects.filter(pk=batch.pk).update(
            created=timezone.now()
            - timedelta(seconds=app_settings.PERSISTENT_REMINDER_PERIOD + 1)
        )
        tasks.send_pending_upgrade_reminders.run()
        self.assertEqual(mocked_notify.call_count, 1)
        kwargs = mocked_notify.call_args.kwargs
        self.assertEqual(kwargs["target"], batch)
        self.assertEqual(kwargs["type"], "pending_upgrade_reminder")
        self.assertIn("pending", str(kwargs["description"]).lower())
        batch.refresh_from_db()
        self.assertIsNotNone(batch.last_reminder_at)

    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_multiple_qualifying_batches_each_fire(self, mocked_notify):
        env = self._create_upgrade_env()
        stale = timezone.now() - timedelta(
            seconds=app_settings.PERSISTENT_REMINDER_PERIOD + 1
        )
        batches = []
        for device_fw in (env["device_fw1"], env["device_fw2"]):
            batch = self._create_persistent_batch(build=env["build1"])
            self._create_pending_op_for_batch(batch, device_fw=device_fw)
            BatchUpgradeOperation.objects.filter(pk=batch.pk).update(created=stale)
            batches.append(batch)
        tasks.send_pending_upgrade_reminders.run()
        self.assertEqual(mocked_notify.call_count, 2)
        notified = {call.kwargs["target"] for call in mocked_notify.call_args_list}
        self.assertEqual(notified, set(batches))

    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_cadence_guard_within_window(self, mocked_notify):
        batch = self._create_persistent_batch()
        self._create_pending_op_for_batch(batch)
        within_window = app_settings.PERSISTENT_REMINDER_PERIOD - 1
        BatchUpgradeOperation.objects.filter(pk=batch.pk).update(
            last_reminder_at=timezone.now() - timedelta(seconds=within_window),
            created=timezone.now() - timedelta(seconds=within_window * 2),
        )
        tasks.send_pending_upgrade_reminders.run()
        mocked_notify.assert_not_called()

    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_cadence_guard_window_elapsed(self, mocked_notify):
        batch = self._create_persistent_batch()
        self._create_pending_op_for_batch(batch)
        BatchUpgradeOperation.objects.filter(pk=batch.pk).update(
            last_reminder_at=timezone.now()
            - timedelta(seconds=app_settings.PERSISTENT_REMINDER_PERIOD + 1),
        )
        tasks.send_pending_upgrade_reminders.run()
        self.assertEqual(mocked_notify.call_count, 1)

    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_brand_new_batch_skips_reminder(self, mocked_notify):
        batch = self._create_persistent_batch()
        self._create_pending_op_for_batch(batch)
        tasks.send_pending_upgrade_reminders.run()
        mocked_notify.assert_not_called()

    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_consecutive_runs_dedupe(self, mocked_notify):
        batch = self._create_persistent_batch()
        self._create_pending_op_for_batch(batch)
        BatchUpgradeOperation.objects.filter(pk=batch.pk).update(
            created=timezone.now()
            - timedelta(seconds=app_settings.PERSISTENT_REMINDER_PERIOD + 1)
        )
        tasks.send_pending_upgrade_reminders.run()
        tasks.send_pending_upgrade_reminders.run()
        self.assertEqual(mocked_notify.call_count, 1)


class TestFailedPersistentUpgradeNotification(TestUpgraderMixin, TransactionTestCase):
    def _create_persistent_op(self, status="in-progress"):
        device_fw = self._create_device_firmware()
        return UpgradeOperation.objects.create(
            device=device_fw.device,
            image=device_fw.image,
            status=status,
            is_persistent=True,
        )

    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_in_progress_to_failed_fires_notification(self, mocked_notify):
        op = self._create_persistent_op(status="in-progress")
        op = UpgradeOperation.objects.get(pk=op.pk)
        op.status = "failed"
        op.save()
        self.assertEqual(mocked_notify.call_count, 1)
        kwargs = mocked_notify.call_args.kwargs
        self.assertEqual(kwargs["target"], op.device)
        self.assertEqual(kwargs["type"], "persistent_upgrade_failed")

    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_pending_to_failed_fires_notification(self, mocked_notify):
        op = self._create_persistent_op(status="pending")
        op = UpgradeOperation.objects.get(pk=op.pk)
        op.status = "failed"
        op.save()
        self.assertEqual(mocked_notify.call_count, 1)

    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_pending_to_pending_stays_silent(self, mocked_notify):
        op = self._create_persistent_op(status="pending")
        op = UpgradeOperation.objects.get(pk=op.pk)
        op.retry_count = 3
        op.save()
        mocked_notify.assert_not_called()

    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_non_persistent_failure_stays_silent(self, mocked_notify):
        op = self._create_persistent_op(status="in-progress")
        UpgradeOperation.objects.filter(pk=op.pk).update(is_persistent=False)
        op = UpgradeOperation.objects.get(pk=op.pk)
        op.status = "failed"
        op.save()
        mocked_notify.assert_not_called()

    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_failed_to_failed_does_not_duplicate(self, mocked_notify):
        op = self._create_persistent_op(status="failed")
        op = UpgradeOperation.objects.get(pk=op.pk)
        op.log = "second save"
        op.save()
        mocked_notify.assert_not_called()

    @mock.patch("openwisp_notifications.signals.notify.send")
    @mock.patch("openwisp_firmware_upgrader.tasks.upgrade_firmware.delay")
    @mock.patch(
        "openwisp_controller.config.base.device.AbstractDevice.is_deactivated",
        return_value=True,
    )
    def test_deactivated_path_fires_notification(
        self, _is_deactivated, _mocked_upgrade, mocked_notify
    ):
        op = self._create_persistent_op(status="pending")
        tasks.retry_pending_upgrade.run(op.pk)
        op.refresh_from_db()
        self.assertEqual(op.status, "failed")
        self.assertEqual(mocked_notify.call_count, 1)

    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_non_recoverable_failure_fires_notification(self, mocked_notify):
        op = self._create_persistent_op(status="in-progress")
        op = UpgradeOperation.objects.get(pk=op.pk)
        op._recoverable_failure_handler(
            recoverable=False, error=ReconnectionFailed("post-flash reconnect failed")
        )
        op.save()
        self.assertEqual(op.status, "failed")
        self.assertEqual(mocked_notify.call_count, 1)


class TestNotificationTypeRegistration(TransactionTestCase):
    def test_pending_upgrade_reminder_registered(self):
        from openwisp_notifications.types import NOTIFICATION_TYPES

        self.assertIn("pending_upgrade_reminder", NOTIFICATION_TYPES)
        config = NOTIFICATION_TYPES["pending_upgrade_reminder"]
        self.assertEqual(config["level"], "info")
        self.assertEqual(config["verb"], "still pending")
        self.assertEqual(config["message"], "{notification.description}")

    def test_persistent_upgrade_failed_registered(self):
        from openwisp_notifications.types import NOTIFICATION_TYPES

        self.assertIn("persistent_upgrade_failed", NOTIFICATION_TYPES)
        config = NOTIFICATION_TYPES["persistent_upgrade_failed"]
        self.assertEqual(config["level"], "error")
        self.assertEqual(config["verb"], "failed")
        self.assertEqual(config["message"], "{notification.description}")
