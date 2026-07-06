from datetime import timedelta
from unittest import mock

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
