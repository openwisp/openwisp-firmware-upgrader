from datetime import timedelta
from unittest import mock

import swapper
from django.db import transaction
from django.test import TransactionTestCase
from django.utils import timezone

from .. import settings as app_settings
from .. import tasks
from ..exceptions import ReconnectionFailed
from ..swapper import load_model
from .base import TestUpgraderMixin, time_travel

UpgradeOperation = load_model("UpgradeOperation")
BatchUpgradeOperation = load_model("BatchUpgradeOperation")


class TestPendingUpgradeReminders(TestUpgraderMixin, TransactionTestCase):
    def _create_due_batch(self):
        """Create a persistent batch with pending work and no recent reminder.

        Its age exceeds the reminder period so the next Beat scan can claim it.
        """
        batch = self._create_batch_upgrade_operation(
            status="in-progress", is_persistent=True
        )
        self._create_pending_op(batch=batch)
        BatchUpgradeOperation.objects.filter(pk=batch.pk).update(
            created=timezone.now()
            - timedelta(seconds=app_settings.PERSISTENT_REMINDER_PERIOD + 1)
        )
        batch.refresh_from_db()
        return batch

    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_ignores_batches_without_pending(self, mocked_notify):
        batch = self._create_batch_upgrade_operation(
            status="in-progress", is_persistent=True
        )
        device_fw = self._create_device_firmware()
        UpgradeOperation.objects.create(
            device=device_fw.device,
            image=device_fw.image,
            batch=batch,
            status="success",
            is_persistent=True,
        )
        mocked_notify.reset_mock()
        tasks.send_pending_upgrade_reminders.run()
        mocked_notify.assert_not_called()

    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_reminds_qualifying_batch(self, mocked_notify):
        batch = self._create_due_batch()
        tasks.send_pending_upgrade_reminders.run()
        self.assertEqual(mocked_notify.call_count, 1)
        kwargs = mocked_notify.call_args.kwargs
        self.assertEqual(kwargs["target"], batch)
        self.assertEqual(kwargs["type"], "generic_message")
        self.assertEqual(
            str(kwargs["message"]),
            f"1 device is still pending in mass upgrade {batch}.",
        )
        self.assertEqual(kwargs["target_url_suffix"], "?status=pending")
        batch.refresh_from_db()
        self.assertIsNotNone(batch.last_reminder_at)

    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_reminder_skips_stale_batch(self, mocked_notify):
        """Skip a reminder if the batch fails after the scanner counts pending work."""
        batch = self._create_due_batch()
        pending_operations = batch.upgradeoperation_set.filter(status="pending")

        def fail_batch_after_count():
            # The scanner saw pending work, but another worker marked the batch
            # failed before the scanner could claim its reminder.
            BatchUpgradeOperation.objects.filter(pk=batch.pk).update(status="failed")
            return 1

        with mock.patch.object(
            type(batch.upgradeoperation_set), "filter", return_value=pending_operations
        ), mock.patch.object(
            pending_operations, "count", side_effect=fail_batch_after_count
        ) as count_pending:
            tasks.send_pending_upgrade_reminders.run()
        count_pending.assert_called_once_with()
        mocked_notify.assert_not_called()
        batch.refresh_from_db()
        self.assertEqual(batch.status, "failed")
        self.assertIsNone(batch.last_reminder_at)

    @mock.patch(
        "openwisp_notifications.signals.notify.send",
        side_effect=RuntimeError("notification backend unavailable"),
    )
    def test_failed_send_records_reminder(self, mocked_notify):
        now = timezone.now()
        batch = self._create_batch_upgrade_operation(
            status="in-progress", is_persistent=True
        )
        self._create_pending_op(batch=batch)
        BatchUpgradeOperation.objects.filter(pk=batch.pk).update(
            created=now - timedelta(seconds=app_settings.PERSISTENT_REMINDER_PERIOD + 1)
        )
        with time_travel(now), self.assertRaisesRegex(
            RuntimeError, "notification backend unavailable"
        ):
            tasks.send_pending_upgrade_reminders.run()
        batch.refresh_from_db()
        self.assertIsNotNone(batch.last_reminder_at)

    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_rolled_back_reminder_stays_silent(self, mocked_notify):
        batch = self._create_due_batch()
        with transaction.atomic():
            tasks.send_pending_upgrade_reminders.run()
            transaction.set_rollback(True)
        mocked_notify.assert_not_called()
        batch.refresh_from_db()
        self.assertIsNone(batch.last_reminder_at)

    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_reminds_all_qualifying_batches(self, mocked_notify):
        env = self._create_upgrade_env()
        stale = timezone.now() - timedelta(
            seconds=app_settings.PERSISTENT_REMINDER_PERIOD + 1
        )
        batches = []
        for device_fw in (env["device_fw1"], env["device_fw2"]):
            batch = self._create_batch_upgrade_operation(
                build=env["build1"], status="in-progress", is_persistent=True
            )
            self._create_pending_op(batch=batch, device_fw=device_fw)
            BatchUpgradeOperation.objects.filter(pk=batch.pk).update(created=stale)
            batches.append(batch)
        tasks.send_pending_upgrade_reminders.run()
        self.assertEqual(mocked_notify.call_count, 2)
        notified = {call.kwargs["target"] for call in mocked_notify.call_args_list}
        self.assertEqual(notified, set(batches))

    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_cadence_blocks_recent_reminder(self, mocked_notify):
        batch = self._create_batch_upgrade_operation(
            status="in-progress", is_persistent=True
        )
        self._create_pending_op(batch=batch)
        within_window = app_settings.PERSISTENT_REMINDER_PERIOD - 1
        BatchUpgradeOperation.objects.filter(pk=batch.pk).update(
            last_reminder_at=timezone.now() - timedelta(seconds=within_window),
            created=timezone.now() - timedelta(seconds=within_window * 2),
        )
        tasks.send_pending_upgrade_reminders.run()
        mocked_notify.assert_not_called()

    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_cadence_allows_elapsed_reminder(self, mocked_notify):
        batch = self._create_batch_upgrade_operation(
            status="in-progress", is_persistent=True
        )
        self._create_pending_op(batch=batch)
        BatchUpgradeOperation.objects.filter(pk=batch.pk).update(
            last_reminder_at=timezone.now()
            - timedelta(seconds=app_settings.PERSISTENT_REMINDER_PERIOD + 1),
        )
        tasks.send_pending_upgrade_reminders.run()
        self.assertEqual(mocked_notify.call_count, 1)

    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_ignores_new_batch(self, mocked_notify):
        batch = self._create_batch_upgrade_operation(
            status="in-progress", is_persistent=True
        )
        self._create_pending_op(batch=batch)
        tasks.send_pending_upgrade_reminders.run()
        mocked_notify.assert_not_called()

    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_consecutive_runs_dedupe(self, mocked_notify):
        self._create_due_batch()
        tasks.send_pending_upgrade_reminders.run()
        tasks.send_pending_upgrade_reminders.run()
        self.assertEqual(mocked_notify.call_count, 1)


class TestFailedPersistentUpgradeNotification(TestUpgraderMixin, TransactionTestCase):
    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_notifies_in_progress_failure(self, mocked_notify):
        op = self._create_upgrade_operation(is_persistent=True, status="in-progress")
        op = UpgradeOperation.objects.get(pk=op.pk)
        op.status = "failed"
        op.save()
        self.assertEqual(mocked_notify.call_count, 1)
        kwargs = mocked_notify.call_args.kwargs
        self.assertEqual(kwargs["target"], op.device)
        self.assertEqual(kwargs["type"], "generic_message")
        self.assertEqual(kwargs.get("target_url_suffix"), "#upgradeoperation_set-group")

        self.assertEqual(
            str(kwargs["message"]),
            f"Persistent upgrade for device {op.device} failed.",
        )

    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_notifies_pending_failure(self, mocked_notify):
        op = self._create_upgrade_operation(is_persistent=True, status="pending")
        op = UpgradeOperation.objects.get(pk=op.pk)
        op.status = "failed"
        op.save()
        self.assertEqual(mocked_notify.call_count, 1)
        self.assertEqual(
            str(mocked_notify.call_args.kwargs["message"]),
            f"Persistent upgrade for device {op.device} failed.",
        )

    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_ignores_pending_updates(self, mocked_notify):
        op = self._create_upgrade_operation(is_persistent=True, status="pending")
        op = UpgradeOperation.objects.get(pk=op.pk)
        op.retry_count = 3
        op.save()
        mocked_notify.assert_not_called()

    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_ignores_nonpersistent_failure(self, mocked_notify):
        op = self._create_upgrade_operation(is_persistent=True, status="in-progress")
        UpgradeOperation.objects.filter(pk=op.pk).update(is_persistent=False)
        op = UpgradeOperation.objects.get(pk=op.pk)
        op.status = "failed"
        op.save()
        mocked_notify.assert_not_called()

    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_does_not_duplicate_failure(self, mocked_notify):
        op = self._create_upgrade_operation(is_persistent=True, status="failed")
        op = UpgradeOperation.objects.get(pk=op.pk)
        op.log = "second save"
        op.save()
        mocked_notify.assert_not_called()

    @mock.patch("openwisp_notifications.signals.notify.send")
    @mock.patch("openwisp_firmware_upgrader.tasks.upgrade_firmware.apply_async")
    def test_ignores_deactivated_operation(self, _mocked_upgrade, mocked_notify):
        op = self._create_upgrade_operation(is_persistent=True, status="pending")
        op.device.deactivate()
        tasks.retry_pending_upgrade.run(op.pk)
        op.refresh_from_db()
        self.assertEqual(op.status, "aborted")
        self.assertEqual(mocked_notify.call_count, 0)

    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_notifies_nonrecoverable_failure(self, mocked_notify):
        op = self._create_upgrade_operation(is_persistent=True, status="in-progress")
        op = UpgradeOperation.objects.get(pk=op.pk)
        op._recoverable_failure_handler(
            recoverable=False, error=ReconnectionFailed("post-flash reconnect failed")
        )
        op.save()
        self.assertEqual(op.status, "failed")
        self.assertEqual(mocked_notify.call_count, 1)
        self.assertEqual(
            str(mocked_notify.call_args.kwargs["message"]),
            f"Persistent upgrade for device {op.device} failed.",
        )

    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_ignores_rolled_back_failure(self, mocked_notify):
        op = self._create_upgrade_operation(is_persistent=True, status="in-progress")
        op = UpgradeOperation.objects.get(pk=op.pk)
        with transaction.atomic():
            op.status = "failed"
            op.save()
            transaction.set_rollback(True)
        mocked_notify.assert_not_called()
        op.refresh_from_db()
        self.assertEqual(op.status, "in-progress")


class TestBatchCompletionNotification(TestUpgraderMixin, TransactionTestCase):
    def _complete_batch(self, index, is_persistent, op_status):
        build = self._create_build(version=f"1.{index}")
        image = self._create_firmware_image(build=build)
        device = self._create_device(
            name=f"device{index}", mac_address=f"00:11:22:33:44:{index:02d}"
        )
        self._create_config(device=device)
        UpgradeOperation.objects.create(
            device=device,
            image=image,
            batch=BatchUpgradeOperation.objects.create(
                build=build, status="in-progress", is_persistent=is_persistent
            ),
            status=op_status,
            is_persistent=is_persistent,
        )
        return BatchUpgradeOperation.objects.get(build=build)

    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_notifies_noncancelled_completion(self, mocked_notify):
        cases = [
            (True, "success", "success", 1),
            (True, "aborted", "failed", 1),
            (True, "cancelled", "cancelled", 0),
            (False, "success", "success", 1),
        ]
        for index, (is_persistent, op_status, batch_status, calls) in enumerate(cases):
            with self.subTest(op_status=op_status, is_persistent=is_persistent):
                mocked_notify.reset_mock()
                batch = self._complete_batch(index, is_persistent, op_status)
                batch.refresh_from_db()
                self.assertEqual(batch.status, batch_status)
                self.assertEqual(mocked_notify.call_count, calls)
                if calls:
                    kwargs = mocked_notify.call_args.kwargs
                    self.assertEqual(kwargs["target"], batch)
                    self.assertEqual(kwargs["type"], "generic_message")
                    self.assertIn(batch.get_status_display(), str(kwargs["message"]))

    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_does_not_duplicate_completion(self, mocked_notify):
        batch = self._complete_batch(0, is_persistent=False, op_status="success")
        self.assertEqual(mocked_notify.call_count, 1)
        mocked_notify.reset_mock()
        batch.save()
        mocked_notify.assert_not_called()

    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_ignores_rolled_back_completion(self, mocked_notify):
        device_fw = self._create_device_firmware()
        build = device_fw.image.build
        batch = BatchUpgradeOperation.objects.create(build=build, status="in-progress")
        operation = UpgradeOperation.objects.create(
            device=device_fw.device,
            image=device_fw.image,
            batch=batch,
            status="in-progress",
        )
        with transaction.atomic():
            operation.status = "success"
            operation.save()
            transaction.set_rollback(True)
        mocked_notify.assert_not_called()
        batch.refresh_from_db()
        self.assertEqual(batch.status, "in-progress")


class TestScheduledUpgradeNotifications(TestUpgraderMixin, TransactionTestCase):
    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_scheduled_started_hook(self, mocked_notify):
        batch = self._create_scheduled_batch()
        batch._scheduled_started()
        self.assertEqual(mocked_notify.call_count, 1)
        kwargs = mocked_notify.call_args.kwargs
        self.assertEqual(kwargs["target"], batch)
        self.assertEqual(kwargs["type"], "generic_message")
        self.assertIn("has started", str(kwargs["message"]))

    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_scheduled_validation_failed_hook(self, mocked_notify):
        batch = self._create_scheduled_batch()
        batch._scheduled_validation_failed()
        self.assertEqual(mocked_notify.call_count, 1)
        kwargs = mocked_notify.call_args.kwargs
        self.assertEqual(kwargs["type"], "generic_message")
        self.assertIn("no eligible devices remained", str(kwargs["message"]))

    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_started_ignores_rollback(self, mocked_notify):
        batch = self._create_scheduled_batch()
        with transaction.atomic():
            batch._scheduled_started()
            transaction.set_rollback(True)
        mocked_notify.assert_not_called()

    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_validation_failed_ignores_rollback(self, mocked_notify):
        batch = self._create_scheduled_batch()
        with transaction.atomic():
            batch._scheduled_validation_failed()
            transaction.set_rollback(True)
        mocked_notify.assert_not_called()

    @mock.patch("openwisp_firmware_upgrader.tasks.batch_upgrade_operation.delay")
    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_due_batch_fires_started_once(self, mocked_notify, mocked_delay):
        env = self._create_upgrade_env()
        self._create_scheduled_batch(
            build=env["build2"], scheduled_at=timezone.now() - timedelta(minutes=1)
        )
        tasks.execute_scheduled_upgrades.run()
        tasks.execute_scheduled_upgrades.run()
        mocked_delay.assert_called_once()
        starts = [
            c
            for c in mocked_notify.call_args_list
            if "has started" in str(c.kwargs.get("message", ""))
        ]
        self.assertEqual(len(starts), 1)

    @mock.patch("openwisp_firmware_upgrader.tasks.batch_upgrade_operation.delay")
    @mock.patch("openwisp_notifications.signals.notify.send")
    def test_ineligible_batch_fires_validation_failed_only(
        self, mocked_notify, mocked_delay
    ):
        batch = self._create_scheduled_batch(
            scheduled_at=timezone.now() - timedelta(minutes=1)
        )
        tasks.execute_scheduled_upgrades.run()
        mocked_delay.assert_not_called()
        batch.refresh_from_db()
        self.assertEqual(batch.status, "failed")
        self.assertEqual(mocked_notify.call_count, 1)
        self.assertIn(
            "no eligible devices remained",
            str(mocked_notify.call_args.kwargs["message"]),
        )

    def test_started_notification_routes_to_org_admin(self):
        Notification = swapper.load_model("openwisp_notifications", "Notification")
        org = self._get_org()
        admin = self._create_administrator(organizations=[org])
        superuser = self._create_admin()
        batch = self._create_scheduled_batch(build=self._create_build())
        batch._scheduled_started()
        self.assertEqual(Notification.objects.filter(recipient=admin).count(), 1)
        self.assertEqual(Notification.objects.filter(recipient=superuser).count(), 1)
