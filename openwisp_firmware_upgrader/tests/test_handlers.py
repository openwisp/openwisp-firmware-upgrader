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
    def _monitoring_instance(self, device):
        return mock.Mock(device=device)

    def _create_pending_op(self, device_fw=None):
        if device_fw is None:
            device_fw = self._create_device_firmware()
        return UpgradeOperation.objects.create(
            device=device_fw.device,
            image=device_fw.image,
            status="pending",
            is_persistent=True,
        )

    @mock.patch(
        "openwisp_firmware_upgrader.base.models.retry_pending_upgrade.apply_async"
    )
    def test_dispatches_retry_when_status_is_ok(self, mocked_dispatch):
        op = self._create_pending_op()
        UpgradeOperation.handle_health_status_changed(
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
        for status in ("critical", "unknown", "problem", "deactivated"):
            UpgradeOperation.handle_health_status_changed(
                sender=mock.Mock(), instance=instance, status=status
            )
        mocked_dispatch.assert_not_called()

    @mock.patch(
        "openwisp_firmware_upgrader.base.models.retry_pending_upgrade.apply_async"
    )
    def test_skips_when_device_has_no_pending_op(self, mocked_dispatch):
        device_fw = self._create_device_firmware()
        UpgradeOperation.handle_health_status_changed(
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
        UpgradeOperation.handle_health_status_changed(
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
        op1 = UpgradeOperation.objects.create(
            device=device_fw.device,
            image=device_fw.image,
            status="pending",
            is_persistent=True,
        )
        op2 = UpgradeOperation.objects.create(
            device=device_fw.device,
            image=device_fw.image,
            status="pending",
            is_persistent=True,
        )
        UpgradeOperation.handle_health_status_changed(
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
        UpgradeOperation.handle_health_status_changed(
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
        UpgradeOperation.handle_health_status_changed(
            sender=mock.Mock(),
            instance=self._monitoring_instance(op.device),
            status="ok",
        )
        self.assertEqual(mocked_upgrade.call_count, 1)
        tasks.retry_pending_upgrade.run(op.pk)
        self.assertEqual(mocked_upgrade.call_count, 1)

    def test_connect_skips_without_monitoring(self):
        config = apps.get_app_config("firmware_upgrader")
        with mock.patch(
            "openwisp_firmware_upgrader.apps.load_model", return_value=None
        ) as mocked_load:
            config.connect_monitoring_signals()
        mocked_load.assert_called_once_with(
            "device_monitoring", "DeviceMonitoring", required=False
        )

    @mock.patch(
        "openwisp_firmware_upgrader.base.models.retry_pending_upgrade.apply_async"
    )
    def test_connects_monitoring_signal(self, mocked_dispatch):
        config = apps.get_app_config("firmware_upgrader")
        signal = Signal()
        fake_signals = mock.Mock(health_status_changed=signal)
        with mock.patch(
            "openwisp_firmware_upgrader.apps.load_model",
            side_effect=lambda app, model, **kw: (
                mock.Mock()
                if (app, model) == ("device_monitoring", "DeviceMonitoring")
                else UpgradeOperation
            ),
        ), mock.patch.dict(
            "sys.modules", {"openwisp_monitoring.device.signals": fake_signals}
        ):
            config.connect_monitoring_signals()
        op = self._create_pending_op()
        signal.send(
            sender=mock.Mock(),
            instance=self._monitoring_instance(op.device),
            status="ok",
        )
        mocked_dispatch.assert_called_once()
        self.assertEqual(mocked_dispatch.call_args.kwargs["args"], [op.pk])


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
