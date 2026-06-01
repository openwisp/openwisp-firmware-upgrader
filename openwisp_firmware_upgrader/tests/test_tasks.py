from datetime import timedelta
from unittest import mock

from celery.exceptions import SoftTimeLimitExceeded
from django.test import TransactionTestCase
from django.utils import timezone

from openwisp_utils.tests import capture_any_output

from .. import settings as app_settings
from .. import tasks
from ..swapper import load_model
from .base import TestUpgraderMixin

BatchUpgradeOperation = load_model("BatchUpgradeOperation")
UpgradeOperation = load_model("UpgradeOperation")


class TestTasks(TestUpgraderMixin, TransactionTestCase):
    _mock_upgrade = "openwisp_firmware_upgrader.upgraders.openwrt.OpenWrt.upgrade"
    _mock_connect = "openwisp_controller.connection.models.DeviceConnection.connect"

    @mock.patch(_mock_upgrade, side_effect=SoftTimeLimitExceeded())
    @mock.patch(
        "openwisp_firmware_upgrader.base.models.AbstractUpgradeOperation.upgrade",
        side_effect=SoftTimeLimitExceeded(),
    )
    @capture_any_output()
    def test_upgrade_firmware_timeout(self, *args):
        with mock.patch(self._mock_connect, return_value=True):
            device_fw = self._create_device_firmware(upgrade=True)
            self.assertEqual(UpgradeOperation.objects.count(), 1)
            uo = device_fw.image.upgradeoperation_set.first()
            self.assertEqual(uo.status, "failed")
            self.assertIn("Operation timed out.", uo.log)

    @mock.patch(_mock_upgrade, return_value=True)
    @mock.patch(
        "openwisp_firmware_upgrader.base.models.AbstractDeviceFirmware.create_upgrade_operation",
        side_effect=SoftTimeLimitExceeded(),
    )
    @capture_any_output()
    def test_batch_upgrade_timeout(self, *args):
        with mock.patch(self._mock_connect, return_value=True):
            env = self._create_upgrade_env()
            batch = BatchUpgradeOperation.objects.create(build=env["build2"])
            # will be executed synchronously due to CELERY_IS_EAGER = True
            tasks.batch_upgrade_operation.delay(batch_id=batch.pk, firmwareless=False)
            self.assertEqual(BatchUpgradeOperation.objects.count(), 1)
            batch = BatchUpgradeOperation.objects.first()
            self.assertEqual(batch.status, "failed")

    @mock.patch(_mock_upgrade, return_value=True)
    @mock.patch("logging.Logger.warning")
    def test_upgrade_firmware_resilience(self, mocked_logger, *args):
        with mock.patch(self._mock_connect, return_value=True):
            upgrade_op_id = UpgradeOperation().id
            tasks.upgrade_firmware.run(upgrade_op_id)
            mocked_logger.assert_called_with(
                f"The UpgradeOperation object with id {upgrade_op_id} has been deleted"
            )

    @mock.patch(_mock_upgrade, return_value=True)
    @mock.patch("logging.Logger.warning")
    def test_batch_upgrade_operation_resilience(self, mocked_logger, *args):
        with mock.patch(self._mock_connect, return_value=True):
            batch_id = BatchUpgradeOperation().id
            tasks.batch_upgrade_operation.run(batch_id=batch_id, firmwareless=False)
            mocked_logger.assert_called_with(
                f"The BatchUpgradeOperation object with id {batch_id} has been deleted"
            )

    def _create_pending_op(
        self, device_fw=None, retry_count=1, next_retry_at=None, is_persistent=True
    ):
        if device_fw is None:
            device_fw = self._create_device_firmware()
        return UpgradeOperation.objects.create(
            device=device_fw.device,
            image=device_fw.image,
            status="pending",
            is_persistent=is_persistent,
            retry_count=retry_count,
            next_retry_at=next_retry_at or timezone.now() - timedelta(minutes=1),
        )

    @mock.patch("openwisp_firmware_upgrader.tasks.retry_pending_upgrade.apply_async")
    def test_check_pending_upgrades_skips_when_nothing_due(self, mocked_dispatch):
        # one op exists but its retry time is in the future
        self._create_pending_op(next_retry_at=timezone.now() + timedelta(hours=1))
        tasks.check_pending_upgrades.run()
        mocked_dispatch.assert_not_called()

    @mock.patch("openwisp_firmware_upgrader.tasks.retry_pending_upgrade.apply_async")
    def test_check_pending_upgrades_only_dispatches_due_ops(self, mocked_dispatch):
        device_fw = self._create_device_firmware()
        due = self._create_pending_op(
            device_fw=device_fw,
            next_retry_at=timezone.now() - timedelta(minutes=5),
        )
        self._create_pending_op(
            device_fw=device_fw,
            next_retry_at=timezone.now() + timedelta(hours=1),
        )
        tasks.check_pending_upgrades.run()
        self.assertEqual(mocked_dispatch.call_count, 1)
        dispatched_args = mocked_dispatch.call_args.kwargs
        self.assertEqual(dispatched_args["args"], [due.pk])
        countdown = dispatched_args["countdown"]
        self.assertGreaterEqual(countdown, 0)
        self.assertLessEqual(
            countdown, app_settings.PERSISTENT_RETRY_OPTIONS["dispatch_jitter"]
        )

    @mock.patch("openwisp_firmware_upgrader.tasks.upgrade_firmware.delay")
    def test_retry_pending_upgrade_happy_path(self, mocked_upgrade):
        op = self._create_pending_op(retry_count=2)
        tasks.retry_pending_upgrade.run(op.pk)
        op.refresh_from_db()
        self.assertEqual(op.status, "in-progress")
        self.assertIn("Persistent retry #2 starting", op.log)
        mocked_upgrade.assert_called_once_with(op.pk)

    @mock.patch("openwisp_firmware_upgrader.tasks.upgrade_firmware.delay")
    def test_retry_pending_upgrade_raced_out(self, mocked_upgrade):
        op = self._create_pending_op()
        # simulate another worker (or admin cancellation) already flipping the status
        UpgradeOperation.objects.filter(pk=op.pk).update(status="in-progress")
        tasks.retry_pending_upgrade.run(op.pk)
        mocked_upgrade.assert_not_called()
        op.refresh_from_db()
        self.assertEqual(op.status, "in-progress")
        self.assertNotIn("Persistent retry", op.log or "")

    @mock.patch("openwisp_firmware_upgrader.tasks.upgrade_firmware.delay")
    @mock.patch(
        "openwisp_controller.config.base.device.AbstractDevice.is_deactivated",
        return_value=True,
    )
    def test_retry_pending_upgrade_deactivated_device(
        self, _is_deactivated, mocked_upgrade
    ):
        op = self._create_pending_op()
        tasks.retry_pending_upgrade.run(op.pk)
        op.refresh_from_db()
        self.assertEqual(op.status, "failed")
        self.assertIn("Device has been deactivated", op.log)
        mocked_upgrade.assert_not_called()

    @mock.patch("openwisp_firmware_upgrader.tasks.upgrade_firmware.delay")
    @mock.patch("openwisp_firmware_upgrader.tasks.logger.warning")
    def test_retry_pending_upgrade_resilience(self, mocked_logger, mocked_upgrade):
        op = self._create_pending_op()
        mocked_qs = mock.MagicMock()
        mocked_qs.get.side_effect = UpgradeOperation.DoesNotExist
        with mock.patch.object(
            UpgradeOperation.objects, "select_related", return_value=mocked_qs
        ):
            tasks.retry_pending_upgrade.run(op.pk)
        mocked_logger.assert_called_with(
            f"The UpgradeOperation object with id {op.pk} has been deleted"
        )
        mocked_upgrade.assert_not_called()
