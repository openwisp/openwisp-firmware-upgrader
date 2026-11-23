from datetime import timedelta
from html import unescape
from unittest import mock

import swapper
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models.signals import post_save
from django.test import TransactionTestCase
from django.utils import timezone
from kombu.exceptions import OperationalError

from .. import tasks
from ..swapper import load_model
from .base import TestUpgraderMixin, time_travel

UpgradeOperation = load_model("UpgradeOperation")
BatchUpgradeOperation = load_model("BatchUpgradeOperation")
Location = swapper.load_model("geo", "Location")
OrganizationUser = swapper.load_model("openwisp_users", "OrganizationUser")

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
            firmwareless=False,
            scheduled_at=future,
            is_persistent=True,
            initiated_by=self._create_admin(),
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
        batch = build.batch_upgrade(
            firmwareless=False, scheduled_at=future, initiated_by=self._create_admin()
        )
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
        batch = build.batch_upgrade(
            firmwareless=False, scheduled_at=future, initiated_by=self._create_admin()
        )
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
        batch = build.batch_upgrade(
            firmwareless=False, scheduled_at=future, initiated_by=self._create_admin()
        )
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
                unescape(str(notify.call_args.kwargs["message"])),
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
        # TransactionTestCase flushes the grants installed by data migrations.
        admin.user_permissions.add(
            Permission.objects.get(
                codename=f"add_{BatchUpgradeOperation._meta.model_name}",
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

    @mock.patch("openwisp_firmware_upgrader.tasks.batch_upgrade_operation.delay")
    def test_scheduler_rejects_missing_initiator(self, dispatch):
        device_firmware = self._create_device_firmware()
        build = device_firmware.image.build

        with self.subTest("no initiator was supplied"):
            batch = self._create_scheduled_batch(build=build)
            with time_travel(batch.scheduled_at + timedelta(seconds=1)):
                tasks.execute_scheduled_upgrades.run()
            batch.refresh_from_db()
            self.assertEqual(batch.status, "failed")
            self.assertEqual(batch.upgradeoperation_set.count(), 0)
            dispatch.assert_not_called()
        batch.delete()

        with self.subTest("the initiator was deleted"):
            initiator = self._create_admin()
            batch = self._create_scheduled_batch(build=build, initiated_by=initiator)
            initiator.delete()
            batch.refresh_from_db()
            self.assertEqual(batch.initiated_by_id, None)
            self.assertEqual(batch.status, "scheduled")
            with time_travel(batch.scheduled_at + timedelta(seconds=1)):
                tasks.execute_scheduled_upgrades.run()
            batch.refresh_from_db()
            self.assertEqual(batch.status, "failed")
            self.assertEqual(batch.upgradeoperation_set.count(), 0)
            dispatch.assert_not_called()

    @mock.patch("openwisp_firmware_upgrader.tasks.batch_upgrade_operation.delay")
    def test_worker_rejects_initiator_deleted_after_dispatch(self, dispatch):
        device_firmware = self._create_device_firmware()
        initiator = self._create_admin()
        batch = self._create_scheduled_batch(
            build=device_firmware.image.build, initiated_by=initiator
        )
        with time_travel(batch.scheduled_at + timedelta(seconds=1)):
            tasks.execute_scheduled_upgrades.run()
        dispatch.assert_called_once()
        initiator.delete()
        batch.refresh_from_db()
        self.assertEqual(batch.initiated_by_id, None)
        self.assertEqual(batch.status, "in-progress")
        with mock.patch(_upgrade_dispatch) as publish:
            tasks.batch_upgrade_operation.run(batch.pk, False)
        batch.refresh_from_db()
        self.assertEqual(batch.status, "failed")
        self.assertEqual(batch.upgradeoperation_set.count(), 0)
        publish.assert_not_called()

    @mock.patch(_upgrade_dispatch)
    def test_immediate_batch_without_initiator_still_launches(self, publish):
        environment = self._create_upgrade_env()
        batch = self._create_batch_upgrade_operation(build=environment["build2"])
        self.assertEqual(batch.initiated_by_id, None)
        self.assertEqual(batch.scheduled_at, None)
        batch.upgrade(firmwareless=False)
        batch.refresh_from_db()
        self.assertEqual(batch.status, "in-progress")
        self.assertEqual(batch.upgradeoperation_set.count(), 2)
        self.assertEqual(publish.call_count, 2)

    @mock.patch("openwisp_firmware_upgrader.tasks.batch_upgrade_operation.delay")
    def test_worker_rechecks_shared_build_target_organizations(self, dispatch):
        managed_org = self._get_org()
        revoked_org = self._create_org(name="Revoked", slug="revoked")
        category = self._create_category(organization=None)
        env = self._create_upgrade_env(category=category, organization=managed_org)
        env["d2"].organization = revoked_org
        env["d2"].save()
        administrator = self._create_administrator(
            organizations=[managed_org, revoked_org]
        )
        # TransactionTestCase flushes the grants installed by data migrations.
        administrator.user_permissions.add(
            Permission.objects.get(
                codename=f"add_{BatchUpgradeOperation._meta.model_name}",
                content_type__app_label=BatchUpgradeOperation._meta.app_label,
            )
        )
        batch = self._create_scheduled_batch(
            build=env["build2"], initiated_by=administrator
        )
        with time_travel(batch.scheduled_at + timedelta(seconds=1)):
            tasks.execute_scheduled_upgrades.run()
        dispatch.assert_called_once()
        OrganizationUser.objects.filter(
            user=administrator, organization=revoked_org
        ).delete()
        with mock.patch(_upgrade_dispatch) as publish:
            tasks.batch_upgrade_operation.run(batch.pk, False)
        publish.assert_not_called()
        batch.refresh_from_db()
        self.assertEqual(batch.status, "failed")
        self.assertEqual(batch.upgradeoperation_set.count(), 0)

    @mock.patch("openwisp_firmware_upgrader.tasks.batch_upgrade_operation.delay")
    def test_launch_rechecks_shared_firmwareless_target_organizations(self, dispatch):
        managed_org = self._get_org()
        revoked_org = self._create_org(name="Revoked", slug="revoked")
        category = self._create_category(organization=None)
        env = self._create_upgrade_env(
            category=category, organization=managed_org, device_firmware=False
        )
        env["d2"].organization = revoked_org
        env["d2"].save()
        operator = self._create_operator(organizations=[managed_org, revoked_org])
        # Isolate batch creation from Build management using a custom role.
        operator.user_permissions.add(
            Permission.objects.get(
                codename=f"add_{BatchUpgradeOperation._meta.model_name}",
                content_type__app_label=BatchUpgradeOperation._meta.app_label,
            )
        )
        batch = self._create_scheduled_batch(
            build=env["build2"], initiated_by=operator, firmwareless=True
        )
        self.assertEqual(batch._initiator_can_launch(), True)
        OrganizationUser.objects.filter(
            user=operator, organization=revoked_org
        ).delete()
        with time_travel(batch.scheduled_at + timedelta(seconds=1)):
            tasks.execute_scheduled_upgrades.run()
        dispatch.assert_not_called()
        batch.refresh_from_db()
        self.assertEqual(batch.status, "failed")
        self.assertEqual(batch.upgradeoperation_set.count(), 0)

    @mock.patch(_upgrade_dispatch)
    def test_queued_batch_fails_when_target_deleted(self, publish):
        device_firmware = self._create_device_firmware()
        build = device_firmware.image.build
        initiator = self._create_admin()
        due = timezone.now() - timedelta(minutes=1)

        with self.subTest("device group deleted while waiting for the worker"):
            group = self._create_device_group(organization=build.category.organization)
            batch = self._create_scheduled_batch(
                build=build,
                group=group,
                initiated_by=initiator,
                scheduled_at=due,
                status="in-progress",
            )
            group.delete()
            batch.refresh_from_db()
            self.assertEqual(batch.group_id, None)
            self.assertEqual(batch.status, "failed")
            tasks.batch_upgrade_operation.run(batch.pk, False)
            batch.refresh_from_db()
            self.assertEqual(batch.status, "failed")
            self.assertEqual(batch.upgradeoperation_set.count(), 0)
            publish.assert_not_called()

        with self.subTest("location deleted while waiting for the worker"):
            location = Location.objects.create(
                name="Office", organization=build.category.organization
            )
            batch = self._create_scheduled_batch(
                build=build,
                location=location,
                initiated_by=initiator,
                scheduled_at=due,
                status="in-progress",
            )
            location.delete()
            batch.refresh_from_db()
            self.assertEqual(batch.location_id, None)
            self.assertEqual(batch.status, "failed")
            tasks.batch_upgrade_operation.run(batch.pk, False)
            batch.refresh_from_db()
            self.assertEqual(batch.status, "failed")
            self.assertEqual(batch.upgradeoperation_set.count(), 0)
            publish.assert_not_called()

    def test_target_deletion_after_child_creation_preserves_batch(self):
        device_firmware = self._create_device_firmware()
        build = device_firmware.image.build
        group = self._create_device_group(organization=build.category.organization)
        batch = self._create_scheduled_batch(
            build=build, group=group, status="in-progress"
        )
        operation = self._create_upgrade_operation(
            device_fw=device_firmware, batch=batch
        )
        group.delete()
        batch.refresh_from_db()
        self.assertEqual(batch.status, "in-progress")
        self.assertEqual(batch.upgradeoperation_set.get().pk, operation.pk)

    @mock.patch(_upgrade_dispatch)
    def test_worker_skips_unmanaged_firmwareless_device_added_after_authorization(
        self, publish
    ):
        managed_org = self._get_org()
        unmanaged_org = self._create_org(name="Unmanaged", slug="unmanaged")
        category = self._create_category(organization=None)
        env = self._create_upgrade_env(
            category=category, organization=managed_org, device_firmware=False
        )
        administrator = self._create_administrator(organizations=[managed_org])
        # TransactionTestCase flushes the grants installed by data migrations.
        administrator.user_permissions.add(
            Permission.objects.get(
                codename=f"add_{BatchUpgradeOperation._meta.model_name}",
                content_type__app_label=BatchUpgradeOperation._meta.app_label,
            )
        )
        batch = self._create_scheduled_batch(
            build=env["build2"],
            initiated_by=administrator,
            firmwareless=True,
            status="in-progress",
        )
        authorize = BatchUpgradeOperation._initiator_can_launch
        added_devices = []

        def authorize_then_add_device(instance):
            self.assertEqual(authorize(instance), True)
            device = self._create_device(
                name="unmanaged-device",
                mac_address="00:22:bb:33:cc:55",
                organization=unmanaged_org,
                model=env["image2a"].boards[0],
            )
            self._create_config(device=device)
            self._create_device_connection(
                device=device, credentials=self._get_credentials(organization=None)
            )
            added_devices.append(device)
            return True

        with mock.patch.object(
            BatchUpgradeOperation,
            "_initiator_can_launch",
            autospec=True,
            side_effect=authorize_then_add_device,
        ):
            batch.upgrade()
        device = added_devices[0]
        DeviceFirmware = load_model("DeviceFirmware")
        self.assertEqual(DeviceFirmware.objects.filter(device=device).exists(), False)
        self.assertEqual(
            batch.upgradeoperation_set.filter(device=device).exists(), False
        )
        self.assertSetEqual(
            set(batch.upgradeoperation_set.values_list("device_id", flat=True)),
            {env["d1"].pk, env["d2"].pk},
        )
        self.assertEqual(publish.call_count, 2)

    @mock.patch(_upgrade_dispatch)
    def test_worker_skips_unmanaged_related_firmware_added_after_authorization(
        self, publish
    ):
        managed_org = self._get_org()
        unmanaged_org = self._create_org(name="Unmanaged", slug="unmanaged")
        category = self._create_category(organization=None)
        env = self._create_upgrade_env(category=category, organization=managed_org)
        administrator = self._create_administrator(organizations=[managed_org])
        # TransactionTestCase flushes the grants installed by data migrations.
        administrator.user_permissions.add(
            Permission.objects.get(
                codename=f"add_{BatchUpgradeOperation._meta.model_name}",
                content_type__app_label=BatchUpgradeOperation._meta.app_label,
            )
        )
        batch = self._create_scheduled_batch(
            build=env["build2"], initiated_by=administrator, status="in-progress"
        )
        authorize = BatchUpgradeOperation._initiator_can_launch
        added_firmwares = []

        def authorize_then_add_firmware(instance):
            self.assertEqual(authorize(instance), True)
            device = self._create_device(
                name="unmanaged-device",
                mac_address="00:22:bb:33:cc:55",
                organization=unmanaged_org,
                model=env["image1a"].boards[0],
            )
            self._create_config(device=device)
            device_firmware = self._create_device_firmware(
                device=device, image=env["image1a"], installed=True
            )
            added_firmwares.append(device_firmware)
            return True

        with mock.patch.object(
            BatchUpgradeOperation,
            "_initiator_can_launch",
            autospec=True,
            side_effect=authorize_then_add_firmware,
        ):
            batch.upgrade()
        device_firmware = added_firmwares[0]
        device_firmware.refresh_from_db()
        self.assertEqual(device_firmware.image_id, env["image1a"].pk)
        self.assertEqual(device_firmware.installed, True)
        self.assertEqual(
            batch.upgradeoperation_set.filter(device=device_firmware.device).exists(),
            False,
        )
        self.assertSetEqual(
            set(batch.upgradeoperation_set.values_list("device_id", flat=True)),
            {env["d1"].pk, env["d2"].pk},
        )
        self.assertEqual(publish.call_count, 2)

    @mock.patch(_upgrade_dispatch)
    def test_worker_reloads_device_organization_before_creating_child(self, publish):
        managed_org = self._get_org()
        unmanaged_org = self._create_org(name="Unmanaged", slug="unmanaged")
        category = self._create_category(organization=None)
        env = self._create_upgrade_env(category=category, organization=managed_org)
        administrator = self._create_administrator(organizations=[managed_org])
        # TransactionTestCase flushes the grants installed by data migrations.
        administrator.user_permissions.add(
            Permission.objects.get(
                codename=f"add_{BatchUpgradeOperation._meta.model_name}",
                content_type__app_label=BatchUpgradeOperation._meta.app_label,
            )
        )
        batch = self._create_scheduled_batch(
            build=env["build2"], initiated_by=administrator, status="in-progress"
        )
        launch = BatchUpgradeOperation._launch_device_firmware

        def move_device_then_launch(instance, device_firmware):
            if device_firmware.device_id == env["d1"].pk:
                # Cache the old relation to ensure launch reloads persisted state.
                self.assertEqual(device_firmware.device.organization_id, managed_org.pk)
                type(env["d1"]).objects.filter(pk=env["d1"].pk).update(
                    organization=unmanaged_org
                )
            return launch(instance, device_firmware)

        with mock.patch.object(
            BatchUpgradeOperation,
            "_launch_device_firmware",
            autospec=True,
            side_effect=move_device_then_launch,
        ):
            batch.upgrade()
        env["device_fw1"].refresh_from_db()
        self.assertEqual(env["device_fw1"].image_id, env["image1a"].pk)
        self.assertEqual(batch.upgradeoperation_set.get().device_id, env["d2"].pk)
        publish.assert_called_once()

    @mock.patch(_upgrade_dispatch)
    @mock.patch("openwisp_firmware_upgrader.tasks.batch_upgrade_operation.delay")
    def test_worker_uses_rescheduled_option_when_old_task_is_replayed(
        self, dispatch, publish
    ):
        env = self._create_upgrade_env()
        env["device_fw2"].delete()
        batch = self._create_scheduled_batch(
            build=env["build2"],
            initiated_by=self._create_admin(),
            firmwareless=True,
        )
        first_launch = batch.scheduled_at + timedelta(seconds=1)
        with time_travel(first_launch):
            tasks.execute_scheduled_upgrades.run()
        dispatch.assert_called_once_with(batch.pk, True)
        batch.refresh_from_db()
        self.assertEqual(batch.status, "in-progress")
        recovered_at = first_launch + timedelta(days=1)
        with time_travel(recovered_at):
            BatchUpgradeOperation._recover_orphaned_launches(recovered_at)
            batch.refresh_from_db()
            self.assertEqual(batch.status, "scheduled")
            new_due = recovered_at + timedelta(hours=1)
            batch.reschedule(scheduled_at=new_due, firmwareless=False)
        with time_travel(new_due + timedelta(seconds=1)):
            tasks.execute_scheduled_upgrades.run()
            self.assertEqual(dispatch.call_count, 2)
            self.assertEqual(dispatch.call_args.args, (batch.pk, False))
            tasks.batch_upgrade_operation.run(batch.pk, True)
        batch.refresh_from_db()
        self.assertEqual(batch.firmwareless, False)
        self.assertEqual(
            batch.upgradeoperation_set.count(),
            1,
            "The replayed task must respect the disabled firmwareless selection.",
        )
        self.assertEqual(batch.upgradeoperation_set.get().device_id, env["d1"].pk)
        self.assertEqual(
            load_model("DeviceFirmware").objects.filter(device=env["d2"]).exists(),
            False,
        )
        publish.assert_called_once()

    @mock.patch(_upgrade_dispatch)
    def test_worker_reloads_saved_firmwareless_option_before_launch(self, publish):
        env = self._create_upgrade_env()
        env["device_fw2"].delete()
        batch = self._create_scheduled_batch(
            build=env["build2"],
            initiated_by=self._create_admin(),
            firmwareless=True,
            status="in-progress",
        )
        BatchUpgradeOperation.objects.filter(pk=batch.pk).update(firmwareless=False)
        batch.upgrade()
        batch.refresh_from_db()
        self.assertEqual(batch.firmwareless, False)
        self.assertEqual(
            batch.upgradeoperation_set.count(),
            1,
            "A stale batch instance must use the saved firmwareless selection.",
        )
        self.assertEqual(batch.upgradeoperation_set.get().device_id, env["d1"].pk)
        publish.assert_called_once()

    @mock.patch(_upgrade_dispatch)
    def test_broker_failure_does_not_skip_later_child_dispatch(self, publish):
        env = self._create_upgrade_env()
        self._create_device_with_connection(
            name="third-device",
            mac_address="00:22:bb:33:cc:66",
            model=env["image2a"].boards[0],
            organization=env["d1"].organization,
        )
        batch = self._create_scheduled_batch(
            build=env["build2"],
            initiated_by=self._create_admin(),
            firmwareless=True,
            is_persistent=False,
            status="in-progress",
        )
        publish.side_effect = [None, OperationalError("broker unavailable"), None]
        with self.assertLogs(
            "openwisp_firmware_upgrader.base.models", level="ERROR"
        ) as logs:
            batch.upgrade()
        self.assertEqual(publish.call_count, 3)
        operations = batch.upgradeoperation_set
        self.assertEqual(operations.count(), 3)
        self.assertEqual(operations.filter(status="in-progress").count(), 3)
        self.assertSetEqual(
            {call.args[0][0] for call in publish.call_args_list},
            set(operations.values_list("pk", flat=True)),
        )
        failed_operation_id = publish.call_args_list[1].args[0][0]
        self.assertIn(str(failed_operation_id), logs.output[0])
        self.assertIn("broker unavailable", logs.output[0])
        batch.upgrade()
        self.assertEqual(publish.call_count, 3)
        self.assertEqual(operations.count(), 3)

    @mock.patch(_upgrade_dispatch, side_effect=OperationalError("broker unavailable"))
    def test_standalone_dispatch_propagates_broker_failure(self, publish):
        device_firmware = self._create_device_firmware()
        with self.assertRaisesRegex(OperationalError, "broker unavailable"):
            device_firmware.create_upgrade_operation(batch=None, upgrade_options={})
        publish.assert_called_once()
        self.assertEqual(UpgradeOperation.objects.count(), 1)

    @mock.patch(_upgrade_dispatch, side_effect=RuntimeError("unexpected worker error"))
    def test_batch_dispatch_propagates_non_broker_failure(self, publish):
        env = self._create_upgrade_env()
        batch = self._create_scheduled_batch(
            build=env["build2"],
            initiated_by=self._create_admin(),
            status="in-progress",
        )
        with self.assertRaisesRegex(RuntimeError, "unexpected worker error"):
            batch.upgrade()
        publish.assert_called_once()
        self.assertEqual(batch.upgradeoperation_set.count(), 2)

    @mock.patch(_upgrade_dispatch)
    def test_rolled_back_batch_does_not_dispatch(self, publish):
        env = self._create_upgrade_env()
        batch = self._create_scheduled_batch(
            build=env["build2"],
            initiated_by=self._create_admin(),
            status="in-progress",
        )
        with transaction.atomic():
            batch.upgrade()
            self.assertEqual(batch.upgradeoperation_set.count(), 2)
            transaction.set_rollback(True)
        publish.assert_not_called()
        self.assertEqual(batch.upgradeoperation_set.count(), 0)

    @mock.patch(_upgrade_dispatch)
    def test_worker_skips_device_deleted_after_selection(self, publish):
        environment = self._create_upgrade_env()
        deleted_device = self._create_device(
            name="device-deleted-during-launch",
            mac_address="00:22:bb:33:cc:66",
            model=environment["image2a"].boards[0],
            organization=environment["d1"].organization,
        )
        batch = self._create_scheduled_batch(
            build=environment["build2"],
            initiated_by=self._create_admin(),
            firmwareless=True,
            status="in-progress",
        )
        deleted_device_id = deleted_device.pk
        launch = BatchUpgradeOperation._launch_device_firmware

        def delete_device_then_launch(instance, device_firmware):
            if device_firmware.device_id == deleted_device_id:
                deleted_device.deactivate()
                # Deactivation queues cache invalidation with this instance.
                # Delete a fresh copy so Django doesn't clear the callback's PK.
                type(deleted_device).objects.get(pk=deleted_device_id).delete()
            return launch(instance, device_firmware)

        with mock.patch.object(
            BatchUpgradeOperation,
            "_launch_device_firmware",
            autospec=True,
            side_effect=delete_device_then_launch,
        ):
            with self.assertLogs(
                "openwisp_firmware_upgrader.base.models", level="WARNING"
            ) as logs:
                batch.upgrade()
        self.assertEqual(
            [entry.getMessage() for entry in logs.records],
            [
                f"Skipped device {deleted_device_id} in mass upgrade {batch}: "
                "device was deleted",
            ],
        )
        batch.refresh_from_db()
        self.assertEqual(batch.status, "in-progress")
        self.assertSetEqual(
            set(batch.upgradeoperation_set.values_list("device_id", flat=True)),
            {environment["d1"].pk, environment["d2"].pk},
        )
        self.assertEqual(publish.call_count, 2)

    def test_reschedule_rejects_disabled_organization(self):
        build = self._create_build()
        batch = self._create_scheduled_batch(build=build)
        original_time = batch.scheduled_at
        organization = build.category.organization
        type(organization).objects.filter(pk=organization.pk).update(is_active=False)

        with self.assertRaises(ValidationError):
            batch.reschedule(scheduled_at=timezone.now() + timedelta(days=2))

        batch.refresh_from_db()
        self.assertEqual(batch.scheduled_at, original_time)
        self.assertEqual(batch.status, "scheduled")
