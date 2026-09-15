from unittest import mock

from celery.signals import worker_ready
from django.core.cache import cache
from django.test import TestCase, override_settings

from openwisp_firmware_upgrader.apps import FirmwareUpdaterConfig
from openwisp_firmware_upgrader.checks import (
    check_extraction_claim_timeout,
    check_reclaim_stale_extractions_scheduled,
)

_MOCK_DELAY = "openwisp_firmware_upgrader.tasks.queue_unconfirmed_extractions.delay"
_LOCK_KEY = "firmware_upgrader.queue_unconfirmed_lock"


class TestWorkerReadySignal(TestCase):
    def setUp(self):
        cache.delete(_LOCK_KEY)

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

    @mock.patch(_MOCK_DELAY)
    def test_failed_call_releases_lock_for_retry(self, mock_delay):
        mock_delay.side_effect = [Exception("broker down"), None]
        FirmwareUpdaterConfig.queue_unconfirmed_extractions_on_worker_ready()
        self.assertIsNone(cache.get(_LOCK_KEY))
        FirmwareUpdaterConfig.queue_unconfirmed_extractions_on_worker_ready()
        self.assertEqual(mock_delay.call_count, 2)

    @mock.patch(_MOCK_DELAY)
    def test_second_call_within_lock_timeout_is_skipped(self, mock_delay):
        FirmwareUpdaterConfig.queue_unconfirmed_extractions_on_worker_ready()
        FirmwareUpdaterConfig.queue_unconfirmed_extractions_on_worker_ready()
        mock_delay.assert_called_once()


class TestChecks(TestCase):
    def test_check_extraction_claim_timeout_ok_by_default(self):
        errors = check_extraction_claim_timeout(None)
        self.assertEqual(errors, [])

    @mock.patch(
        "openwisp_firmware_upgrader.checks.app_settings.EXTRACTION_CLAIM_TIMEOUT", 60
    )
    @mock.patch("openwisp_firmware_upgrader.checks.app_settings.TASK_TIMEOUT", 1500)
    def test_check_extraction_claim_timeout_warns_when_lower(self):
        errors = check_extraction_claim_timeout(None)
        self.assertEqual(len(errors), 1)
        self.assertIn("EXTRACTION_CLAIM_TIMEOUT", errors[0].msg)

    @override_settings(CELERY_BEAT_SCHEDULE={})
    def test_check_reclaim_stale_extractions_scheduled_warns_when_missing(self):
        errors = check_reclaim_stale_extractions_scheduled(None)
        self.assertEqual(len(errors), 1)
        self.assertIn("reclaim_stale_extractions", errors[0].msg)

    @override_settings(
        CELERY_BEAT_SCHEDULE={
            "reclaim_stale_extractions": {
                "task": "openwisp_firmware_upgrader.tasks.reclaim_stale_extractions",
                "schedule": 900,
            }
        }
    )
    def test_check_reclaim_stale_extractions_scheduled_ok(self):
        errors = check_reclaim_stale_extractions_scheduled(None)
        self.assertEqual(errors, [])
