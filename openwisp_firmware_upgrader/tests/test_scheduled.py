from datetime import timedelta
from unittest import mock

from django.db.models.signals import post_save
from django.test import TransactionTestCase
from django.utils import timezone

from .. import tasks
from ..exceptions import RecoverableFailure
from ..swapper import load_model
from .base import TestUpgraderMixin, time_travel

UpgradeOperation = load_model("UpgradeOperation")
BatchUpgradeOperation = load_model("BatchUpgradeOperation")

_upgrade_delay = "openwisp_firmware_upgrader.tasks.upgrade_firmware.delay"
_connect = "openwisp_controller.connection.models.DeviceConnection.connect"


class TestScheduledExecution(TestUpgraderMixin, TransactionTestCase):
    def _schedule(self, at, **kwargs):
        device_fw = self._create_device_firmware()
        return device_fw.image.build.batch_upgrade(
            firmwareless=False, scheduled_at=at, **kwargs
        )

    def test_scheduled_persistent_offline_device_recovers(self):
        future = timezone.now() + timedelta(days=1)
        batch = self._schedule(future, is_persistent=True)

        def pend(operation_id):
            op = UpgradeOperation.objects.get(pk=operation_id)
            op._recoverable_failure_handler(
                recoverable=False, error=RecoverableFailure("device offline")
            )
            op.save()

        due = future + timedelta(seconds=1)
        with time_travel(due), mock.patch(_connect, return_value=True), mock.patch(
            _upgrade_delay, side_effect=pend
        ):
            tasks.execute_scheduled_upgrades.run()

        op = batch.upgradeoperation_set.get()
        self.assertTrue(op.is_persistent)
        self.assertEqual(op.status, "pending")
        self.assertEqual(op.retry_count, 1)
        self.assertGreater(op.next_retry_at, due)
        batch.refresh_from_db()
        self.assertEqual(batch.status, "in-progress")

        def succeed(operation_id):
            recovered = UpgradeOperation.objects.get(pk=operation_id)
            recovered.status = "success"
            recovered.save()

        with time_travel(op.next_retry_at + timedelta(seconds=1)), mock.patch(
            _upgrade_delay, side_effect=succeed
        ):
            tasks.check_pending_upgrades.run()

        op.refresh_from_db()
        self.assertEqual(op.status, "success")
        batch.refresh_from_db()
        self.assertEqual(batch.status, "success")

    @mock.patch("openwisp_firmware_upgrader.tasks.batch_upgrade_operation.delay")
    def test_conflict_at_launch_fails_batch_without_duplicate(self, mocked_dispatch):
        # A per-device operation acquired after scheduling must be detected at
        # launch: the batch fails instead of double-flashing the device.
        device_fw = self._create_device_firmware()
        build = device_fw.image.build
        future = timezone.now() + timedelta(days=1)
        batch = build.batch_upgrade(firmwareless=False, scheduled_at=future)
        UpgradeOperation.objects.create(
            device=device_fw.device,
            image=device_fw.image,
            status="in-progress",
        )
        with time_travel(future + timedelta(seconds=1)):
            tasks.execute_scheduled_upgrades.run()
        mocked_dispatch.assert_not_called()
        batch.refresh_from_db()
        self.assertEqual(batch.status, "failed")
        self.assertEqual(batch.upgradeoperation_set.count(), 0)
        self.assertEqual(UpgradeOperation.objects.count(), 1)

    @mock.patch("openwisp_firmware_upgrader.tasks.batch_upgrade_operation.delay")
    def test_cancel_before_worker_populates_stops_flash(self, mocked_dispatch):
        # Simulate the claim->worker window: the Beat claims the batch and
        # dispatches, but the worker has not run yet (delay mocked). A cancel
        # landing now must stop the flash and leave the batch cancelled.
        device_fw = self._create_device_firmware()
        build = device_fw.image.build
        future = timezone.now() + timedelta(days=1)
        batch = build.batch_upgrade(firmwareless=False, scheduled_at=future)
        with time_travel(future + timedelta(seconds=1)):
            tasks.execute_scheduled_upgrades.run()
        mocked_dispatch.assert_called_once()
        batch.refresh_from_db()
        self.assertEqual(batch.status, "in-progress")
        self.assertEqual(batch.upgradeoperation_set.count(), 0)
        batch.cancel()
        batch.refresh_from_db()
        self.assertEqual(batch.status, "cancelled")
        with mock.patch(_upgrade_delay) as mocked_upgrade:
            tasks.batch_upgrade_operation.run(batch.pk, batch.firmwareless)
        batch.refresh_from_db()
        self.assertEqual(batch.status, "cancelled")
        self.assertEqual(batch.upgradeoperation_set.count(), 0)
        mocked_upgrade.assert_not_called()

    def test_dispatch_failure_reverts_to_scheduled(self):
        device_fw = self._create_device_firmware()
        build = device_fw.image.build
        future = timezone.now() + timedelta(days=1)
        batch = build.batch_upgrade(firmwareless=False, scheduled_at=future)
        with time_travel(future + timedelta(seconds=1)), mock.patch(
            "openwisp_firmware_upgrader.tasks.batch_upgrade_operation.delay",
            side_effect=RuntimeError("broker down"),
        ), mock.patch.object(BatchUpgradeOperation, "_scheduled_started") as started:
            tasks.execute_scheduled_upgrades.run()
        batch.refresh_from_db()
        self.assertEqual(batch.status, "scheduled")
        started.assert_not_called()
        self.assertEqual(batch.upgradeoperation_set.count(), 0)

    @mock.patch("openwisp_firmware_upgrader.tasks.batch_upgrade_operation.delay")
    def test_failed_cas_respects_reschedule_into_future(self, mocked_dispatch):
        # A reschedule committing between the due-scan and the failed CAS must
        # not flip a now-future batch to failed.
        build = self._create_build()
        future = timezone.now() + timedelta(days=1)
        batch = BatchUpgradeOperation.objects.create(
            build=build, status="scheduled", scheduled_at=future
        )
        real_dry_run = BatchUpgradeOperation.dry_run

        def reschedule(build, group=None, location=None):
            BatchUpgradeOperation.objects.filter(pk=batch.pk).update(
                scheduled_at=timezone.now() + timedelta(days=2)
            )
            return real_dry_run(build=build, group=group, location=location)

        with time_travel(future + timedelta(seconds=1)), mock.patch.object(
            BatchUpgradeOperation, "dry_run", side_effect=reschedule
        ):
            tasks.execute_scheduled_upgrades.run()
        mocked_dispatch.assert_not_called()
        batch.refresh_from_db()
        self.assertEqual(batch.status, "scheduled")

    def test_scheduled_failed_emits_post_save(self):
        build = self._create_build()
        future = timezone.now() + timedelta(days=1)
        batch = BatchUpgradeOperation.objects.create(
            build=build, status="scheduled", scheduled_at=future
        )
        seen = []

        def receiver(sender, instance, **kwargs):
            if instance.pk == batch.pk:
                seen.append(instance.status)

        post_save.connect(receiver, sender=BatchUpgradeOperation)
        try:
            with time_travel(future + timedelta(seconds=1)):
                tasks.execute_scheduled_upgrades.run()
        finally:
            post_save.disconnect(receiver, sender=BatchUpgradeOperation)
        self.assertIn("failed", seen)
        batch.refresh_from_db()
        self.assertEqual(batch.status, "failed")
