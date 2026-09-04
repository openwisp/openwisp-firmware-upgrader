from unittest import mock

from celery.signals import worker_ready
from django.test import TestCase

from openwisp_firmware_upgrader.apps import FirmwareUpdaterConfig

_MOCK_DELAY = "openwisp_firmware_upgrader.tasks.queue_unconfirmed_extractions.delay"


class TestWorkerReadySignal(TestCase):
    @mock.patch(_MOCK_DELAY)
    def test_queue_unconfirmed_extractions_on_worker_ready(self, mock_delay):
        FirmwareUpdaterConfig.queue_unconfirmed_extractions_on_worker_ready()
        mock_delay.assert_called_once()

    @mock.patch(_MOCK_DELAY)
    def test_worker_ready_signal_triggers_queueing(self, mock_delay):
        worker_ready.send(sender=None)
        mock_delay.assert_called_once()

    @mock.patch(_MOCK_DELAY)
    def test_disabled_via_setting(self, mock_delay):
        with mock.patch(
            "openwisp_firmware_upgrader.apps.app_settings.QUEUE_UNCONFIRMED_ON_WORKER_READY",
            False,
        ):
            FirmwareUpdaterConfig.queue_unconfirmed_extractions_on_worker_ready()
        mock_delay.assert_not_called()
