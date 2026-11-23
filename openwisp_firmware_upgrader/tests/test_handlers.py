from unittest import mock

from django.apps import apps
from django.dispatch import Signal
from django.test import TransactionTestCase

from openwisp_utils.tests import catch_signal

from .. import settings as app_settings
from .. import tasks
from ..signals import firmware_upgrader_log_updated
from ..swapper import load_model
from .base import TestUpgraderMixin

UpgradeOperation = load_model("UpgradeOperation")


class TestMonitoringSignalHandler(TestUpgraderMixin, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.health_status_changed = Signal()
        self.addCleanup(
            self.health_status_changed.disconnect,
            dispatch_uid="firmware_upgrader.health_status_changed",
        )
        config = apps.get_app_config(UpgradeOperation._meta.app_label)
        signals = mock.Mock(health_status_changed=self.health_status_changed)
        with mock.patch(
            "openwisp_firmware_upgrader.apps.load_model",
            side_effect=[mock.sentinel.device_monitoring, UpgradeOperation],
        ), mock.patch.dict(
            "sys.modules", {"openwisp_monitoring.device.signals": signals}
        ):
            config.connect_monitoring_signals()

    def _monitoring_instance(self, device):
        return mock.Mock(device=device)

    @mock.patch(
        "openwisp_firmware_upgrader.base.models.retry_pending_upgrade.apply_async"
    )
    def test_dispatches_retry_when_status_is_ok(self, mocked_dispatch):
        op = self._create_pending_op()
        self.health_status_changed.send(
            sender=mock.Mock(),
            instance=self._monitoring_instance(op.device),
            status="ok",
        )
        self.assertEqual(mocked_dispatch.call_count, 1)
        kwargs = mocked_dispatch.call_args.kwargs
        self.assertEqual(kwargs["args"], [op.pk])
        self.assertGreaterEqual(kwargs["countdown"], 0)
        self.assertLessEqual(
            kwargs["countdown"],
            app_settings.PERSISTENT_RETRY_OPTIONS["signal_jitter"],
        )

    @mock.patch(
        "openwisp_firmware_upgrader.base.models.retry_pending_upgrade.apply_async"
    )
    def test_ignores_non_ok_statuses(self, mocked_dispatch):
        op = self._create_pending_op()
        instance = self._monitoring_instance(op.device)
        with self.subTest("critical device is not retried"):
            self.health_status_changed.send(
                sender=mock.Mock(), instance=instance, status="critical"
            )
            mocked_dispatch.assert_not_called()

        with self.subTest("unknown health is not retried"):
            self.health_status_changed.send(
                sender=mock.Mock(), instance=instance, status="unknown"
            )
            mocked_dispatch.assert_not_called()

        with self.subTest("problem device is not retried"):
            self.health_status_changed.send(
                sender=mock.Mock(), instance=instance, status="problem"
            )
            mocked_dispatch.assert_not_called()

        with self.subTest("deactivated device is not retried"):
            self.health_status_changed.send(
                sender=mock.Mock(), instance=instance, status="deactivated"
            )
            mocked_dispatch.assert_not_called()

    @mock.patch(
        "openwisp_firmware_upgrader.base.models.retry_pending_upgrade.apply_async"
    )
    def test_skips_when_device_has_no_pending_op(self, mocked_dispatch):
        device_fw = self._create_device_firmware()
        self.health_status_changed.send(
            sender=mock.Mock(),
            instance=self._monitoring_instance(device_fw.device),
            status="ok",
        )
        mocked_dispatch.assert_not_called()

    @mock.patch(
        "openwisp_firmware_upgrader.base.models.retry_pending_upgrade.apply_async"
    )
    def test_skips_when_existing_op_is_not_pending(self, mocked_dispatch):
        device_fw = self._create_device_firmware()
        UpgradeOperation.objects.create(
            device=device_fw.device,
            image=device_fw.image,
            status="in-progress",
            is_persistent=True,
        )
        self.health_status_changed.send(
            sender=mock.Mock(),
            instance=self._monitoring_instance(device_fw.device),
            status="ok",
        )
        mocked_dispatch.assert_not_called()

    @mock.patch(
        "openwisp_firmware_upgrader.base.models.retry_pending_upgrade.apply_async"
    )
    def test_dispatches_pending_operations(self, mocked_dispatch):
        device_fw = self._create_device_firmware()
        op1 = self._create_pending_op(device_fw=device_fw)
        op2 = self._create_pending_op(device_fw=device_fw)
        self.health_status_changed.send(
            sender=mock.Mock(),
            instance=self._monitoring_instance(device_fw.device),
            status="ok",
        )
        self.assertEqual(mocked_dispatch.call_count, 2)
        dispatched_pks = {
            call.kwargs["args"][0] for call in mocked_dispatch.call_args_list
        }
        self.assertEqual(dispatched_pks, {op1.pk, op2.pk})

    @mock.patch(
        "openwisp_firmware_upgrader.base.models.retry_pending_upgrade.apply_async"
    )
    def test_ignores_other_devices(self, mocked_dispatch):
        own = self._create_pending_op()
        other_image = self._create_firmware_image(type=self.TPLINK_4300_IL_IMAGE)
        other_device = self._create_device(
            name="other-device",
            mac_address="00:99:aa:bb:cc:dd",
            organization=other_image.build.category.organization,
        )
        self._create_config(device=other_device)
        UpgradeOperation.objects.create(
            device=other_device,
            image=other_image,
            status="pending",
            is_persistent=True,
        )
        self.health_status_changed.send(
            sender=mock.Mock(),
            instance=self._monitoring_instance(own.device),
            status="ok",
        )
        self.assertEqual(mocked_dispatch.call_count, 1)
        self.assertEqual(mocked_dispatch.call_args.kwargs["args"], [own.pk])

    @mock.patch("openwisp_firmware_upgrader.tasks.upgrade_firmware.apply_async")
    def test_concurrent_dispatches_once(self, mocked_upgrade):
        """A signal and periodic scan cannot dispatch one pending upgrade twice."""
        op = self._create_pending_op()
        self.health_status_changed.send(
            sender=mock.Mock(),
            instance=self._monitoring_instance(op.device),
            status="ok",
        )
        self.assertEqual(mocked_upgrade.call_count, 1)
        tasks.retry_pending_upgrade.run(op.pk)
        self.assertEqual(mocked_upgrade.call_count, 1)

    def test_connect_skips_without_monitoring(self):
        config = apps.get_app_config(UpgradeOperation._meta.app_label)
        with mock.patch(
            "openwisp_firmware_upgrader.apps.load_model", return_value=None
        ) as mocked_load:
            config.connect_monitoring_signals()
        mocked_load.assert_called_once_with(
            "device_monitoring", "DeviceMonitoring", required=False
        )


class TestLogSignal(TestUpgraderMixin, TransactionTestCase):
    def test_log_line_emits_signal(self):
        device_fw = self._create_device_firmware()
        op = UpgradeOperation.objects.create(
            device=device_fw.device, image=device_fw.image, status="in-progress"
        )
        with catch_signal(firmware_upgrader_log_updated) as handler:
            op.log_line("flashing image", save=True)
        handler.assert_called_once()
        kwargs = handler.call_args.kwargs
        self.assertEqual(kwargs["instance"], op)
        self.assertEqual(kwargs["line"], "flashing image")
