from datetime import timedelta
from unittest import mock

import swapper
from django.contrib.auth.models import Permission
from django.db import transaction
from django.db.models.signals import post_save
from django.test import TransactionTestCase
from django.utils import timezone

from .. import tasks
from ..swapper import load_model
from .base import TestUpgraderMixin, time_travel

UpgradeOperation = load_model("UpgradeOperation")
BatchUpgradeOperation = load_model("BatchUpgradeOperation")
Location = swapper.load_model("geo", "Location")

_upgrade_dispatch = "openwisp_firmware_upgrader.tasks.upgrade_firmware.apply_async"
DeviceConnection = swapper.load_model("connection", "DeviceConnection")


class TestScheduledExecution(TestUpgraderMixin, TransactionTestCase):
    _mock_connect = f"{DeviceConnection.__module__}.DeviceConnection.connect"

    @mock.patch.object(tasks.upgrade_firmware, "max_retries", 0)
    @mock.patch(
        "openwisp_firmware_upgrader.upgraders.openwrt.OpenWrt.upgrade",
        return_value=True,
    )
    def test_scheduled_persistent_offline_device_recovers(self, flash):
        env = self._create_upgrade_env()
        future = timezone.now() + timedelta(days=1)
        batch = env["build2"].batch_upgrade(
            firmwareless=False, scheduled_at=future, is_persistent=True
        )
        offline_device = env["d2"]

        def connect(connection):
            return connection.device_id != offline_device.pk

        due = future + timedelta(seconds=1)
        with time_travel(due), mock.patch(
            self._mock_connect, autospec=True, side_effect=connect
        ):
            tasks.execute_scheduled_upgrades.run()
        # The reachable device finishes during the scheduled launch.
        online_op = batch.upgradeoperation_set.get(device=env["d1"])
        self.assertEqual(online_op.status, "success")
        env["device_fw1"].refresh_from_db()
        self.assertEqual(env["device_fw1"].image, env["image2a"])
        self.assertEqual(env["device_fw1"].installed, True)
        # The offline device keeps the batch open until a later retry succeeds.
        op = batch.upgradeoperation_set.get(device=offline_device)
        self.assertEqual(op.is_persistent, True)
        self.assertEqual(op.status, "pending")
        self.assertEqual(op.retry_count, 1)
        self.assertGreater(op.next_retry_at, due)
        batch.refresh_from_db()
        self.assertEqual(batch.status, "in-progress")
        env["device_fw2"].refresh_from_db()
        self.assertEqual(env["device_fw2"].installed, False)
        first_retry = op.next_retry_at
        with time_travel(first_retry + timedelta(seconds=1)), mock.patch(
            self._mock_connect, autospec=True, side_effect=connect
        ):
            tasks.check_pending_upgrades.run()
        op.refresh_from_db()
        self.assertEqual(op.status, "pending")
        self.assertEqual(op.retry_count, 2)
        self.assertGreater(op.next_retry_at, first_retry)
        batch.refresh_from_db()
        self.assertEqual(batch.status, "in-progress")
        with time_travel(op.next_retry_at + timedelta(seconds=1)), mock.patch(
            self._mock_connect, return_value=True
        ):
            tasks.check_pending_upgrades.run()

        op.refresh_from_db()
        self.assertEqual(op.status, "success")
        batch.refresh_from_db()
        self.assertEqual(batch.status, "success")
        self.assertEqual(batch.upgradeoperation_set.count(), 2)
        env["device_fw2"].refresh_from_db()
        self.assertEqual(env["device_fw2"].image, env["image2b"])
        self.assertEqual(env["device_fw2"].installed, True)
        self.assertEqual(flash.call_count, 2)

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
        cancelled_at = future + timedelta(hours=1)
        with time_travel(cancelled_at):
            batch.cancel()
        batch.refresh_from_db()
        self.assertEqual(batch.status, "cancelled")
        self.assertEqual(batch.modified, cancelled_at)
        with mock.patch(_upgrade_dispatch) as mocked_upgrade:
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
    def test_launch_fails_when_initiator_deactivated(self, dispatch):
        device_fw = self._create_device_firmware()
        org = device_fw.image.build.category.organization
        admin = self._create_administrator(organizations=[org])
        future = timezone.now() + timedelta(days=1)
        batch = device_fw.image.build.batch_upgrade(
            firmwareless=False, scheduled_at=future, initiated_by=admin
        )
        admin.is_active = False
        admin.save(update_fields=["is_active"])
        with time_travel(future + timedelta(seconds=1)):
            tasks.execute_scheduled_upgrades.run()
        dispatch.assert_not_called()
        batch.refresh_from_db()
        self.assertEqual(batch.status, "failed")

    @mock.patch("openwisp_firmware_upgrader.tasks.batch_upgrade_operation.delay")
    def test_worker_rejects_initiator_deactivated_after_dispatch(self, dispatch):
        device_fw = self._create_device_firmware()
        admin = self._create_admin()
        future = timezone.now() + timedelta(days=1)
        batch = device_fw.image.build.batch_upgrade(
            firmwareless=False, scheduled_at=future, initiated_by=admin
        )
        with time_travel(future + timedelta(seconds=1)):
            tasks.execute_scheduled_upgrades.run()
        dispatch.assert_called_once()
        # Cache the active user on a stale batch to exercise the locked reload.
        batch.refresh_from_db()
        self.assertEqual(batch.initiated_by.is_active, True)
        admin.is_active = False
        admin.save(update_fields=["is_active"])
        failed_at = future + timedelta(minutes=1)
        with time_travel(failed_at), mock.patch(
            "openwisp_notifications.signals.notify.send"
        ) as notify, mock.patch(_upgrade_dispatch) as upgrade:
            with self.subTest(
                "rolled back failure does not notify"
            ), transaction.atomic():
                batch.upgrade()
                transaction.set_rollback(True)
            notify.assert_not_called()

            with self.subTest("worker refuses the queued launch"):
                tasks.batch_upgrade_operation.run(batch.pk, batch.firmwareless)
            notify.assert_called_once()
            self.assertEqual(
                str(notify.call_args.kwargs["message"]),
                f"Scheduled mass upgrade {batch} was not started: "
                "the user who scheduled it no longer has permission to run it",
            )
            upgrade.assert_not_called()
        batch.refresh_from_db()
        self.assertEqual(batch.status, "failed")
        self.assertEqual(batch.modified, failed_at)
        self.assertEqual(batch.upgradeoperation_set.count(), 0)

    def test_worker_updates_empty_failure_timestamp(self):
        empty = BatchUpgradeOperation.objects.create(
            build=self._create_build(version="empty"), firmwareless=False
        )
        failed_at = timezone.now() + timedelta(hours=1)
        with time_travel(failed_at), mock.patch(
            "openwisp_notifications.signals.notify.send"
        ) as notify:
            tasks.batch_upgrade_operation.run(empty.pk, False)
        empty.refresh_from_db()
        self.assertEqual(empty.status, "failed")
        self.assertEqual(empty.modified, failed_at)
        self.assertEqual(empty.upgradeoperation_set.count(), 0)
        notify.assert_called_once()

    @mock.patch("openwisp_firmware_upgrader.tasks.batch_upgrade_operation.delay")
    def test_launch_fails_when_initiator_loses_org_access(self, dispatch):
        device_fw = self._create_device_firmware()
        admin = self._create_administrator(organizations=[])
        future = timezone.now() + timedelta(days=1)
        batch = device_fw.image.build.batch_upgrade(
            firmwareless=False, scheduled_at=future, initiated_by=admin
        )
        with time_travel(future + timedelta(seconds=1)):
            tasks.execute_scheduled_upgrades.run()
        dispatch.assert_not_called()
        batch.refresh_from_db()
        self.assertEqual(batch.status, "failed")

    @mock.patch("openwisp_firmware_upgrader.tasks.batch_upgrade_operation.delay")
    def test_launch_proceeds_for_authorized_initiator(self, dispatch):
        device_fw = self._create_device_firmware()
        org = device_fw.image.build.category.organization
        admin = self._create_administrator(organizations=[org])
        admin.user_permissions.add(
            Permission.objects.get(
                codename="add_batchupgradeoperation",
                content_type__app_label=BatchUpgradeOperation._meta.app_label,
            )
        )
        future = timezone.now() + timedelta(days=1)
        batch = device_fw.image.build.batch_upgrade(
            firmwareless=False, scheduled_at=future, initiated_by=admin
        )
        with time_travel(future + timedelta(seconds=1)):
            tasks.execute_scheduled_upgrades.run()
        dispatch.assert_called_once()
        batch.refresh_from_db()
        self.assertEqual(batch.status, "in-progress")

    def test_scheduled_batch_failed_when_group_deleted(self):
        build = self._create_build()
        org = build.category.organization
        group = self._create_device_group(organization=org)
        batch = BatchUpgradeOperation.objects.create(
            build=build,
            status="scheduled",
            scheduled_at=timezone.now() + timedelta(days=1),
            group=group,
        )
        group.delete()
        batch.refresh_from_db()
        self.assertEqual(batch.status, "failed")

    def test_scheduled_batch_failed_when_location_deleted(self):
        build = self._create_build()
        org = build.category.organization
        location = Location.objects.create(
            name="Office A", address="123 Main St", organization=org
        )
        batch = BatchUpgradeOperation.objects.create(
            build=build,
            status="scheduled",
            scheduled_at=timezone.now() + timedelta(days=1),
            location=location,
        )
        location.delete()
        batch.refresh_from_db()
        self.assertEqual(batch.status, "failed")

    def test_target_delete_leaves_unrelated_and_non_scheduled(self):
        build = self._create_build()
        org = build.category.organization
        # deleting a group or location with no scheduled batch must not raise
        self._create_device_group(name="unrelated", organization=org).delete()
        Location.objects.create(name="Empty", address="0", organization=org).delete()
        # a non-scheduled batch targeting a group is left untouched
        group = self._create_device_group(name="in-progress-group", organization=org)
        batch = BatchUpgradeOperation.objects.create(
            build=build, status="in-progress", group=group
        )
        group.delete()
        batch.refresh_from_db()
        self.assertEqual(batch.status, "in-progress")

    def test_recover_orphaned_launches(self):
        Batch = BatchUpgradeOperation
        due = timezone.now() - timedelta(minutes=5)
        stale = timezone.now() - timedelta(hours=1)
        build = self._create_build()
        orphan = Batch.objects.create(
            build=build, status="in-progress", scheduled_at=due
        )
        Batch.objects.filter(pk=orphan.pk).update(modified=stale)
        fresh = Batch.objects.create(
            build=build, status="in-progress", scheduled_at=due
        )
        started = Batch.objects.create(
            build=build, status="in-progress", scheduled_at=due
        )
        device_fw = self._create_device_firmware()
        UpgradeOperation.objects.create(
            device=device_fw.device, image=device_fw.image, batch=started
        )
        Batch.objects.filter(pk=started.pk).update(modified=stale)
        Batch._recover_orphaned_launches(timezone.now())
        orphan.refresh_from_db()
        fresh.refresh_from_db()
        started.refresh_from_db()
        self.assertEqual(orphan.status, "scheduled")
        self.assertEqual(fresh.status, "in-progress")
        self.assertEqual(started.status, "in-progress")

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
