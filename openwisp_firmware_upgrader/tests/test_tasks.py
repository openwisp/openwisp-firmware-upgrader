import uuid
from datetime import timedelta
from unittest import mock

from celery.exceptions import SoftTimeLimitExceeded
from django.db.models.query import QuerySet
from django.test import TransactionTestCase
from django.utils import timezone
from openwisp_notifications.swapper import load_model as load_notification_model

from openwisp_utils.tests import capture_any_output

from .. import settings as app_settings
from .. import tasks, utils
from ..extractors.exceptions import DecompressionLimitExceeded, UnsupportedImageError
from ..swapper import load_model
from .base import TestUpgraderMixin

BatchUpgradeOperation = load_model("BatchUpgradeOperation")
FirmwareImage = load_model("FirmwareImage")
UpgradeOperation = load_model("UpgradeOperation")
Notification = load_notification_model("Notification")
NotificationSetting = load_notification_model("NotificationSetting")

_MOCK_EXTRACTOR = (
    "openwisp_firmware_upgrader.base.models.AbstractCategory.metadata_extractor_class"
)
_MOCK_NOTIFY = "openwisp_notifications.signals.notify.send"


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

    @mock.patch(_MOCK_EXTRACTOR)
    @capture_any_output()
    def test_extract_firmware_metadata_success(self, MockExtractor, *args):
        MockExtractor.return_value.extract.return_value = {
            "model": "TP-Link WDR4300",
            "compatible": ["tplink,tl-wdr4300-v1"],
            "target": "ath79/generic",
            "version": "23.05.5",
            "compat_version": "1.0",
            "source": "fwtool",
        }
        image = self._create_firmware_image()
        FirmwareImage.objects.filter(pk=image.pk).update(
            extraction_status=FirmwareImage.STATUS_UNCONFIRMED
        )
        tasks.extract_firmware_metadata.run(str(image.pk))
        image.refresh_from_db()
        self.assertEqual(image.extraction_status, FirmwareImage.STATUS_SUCCESS)
        self.assertEqual(image.board, "TP-Link WDR4300")
        self.assertEqual(image.target, "ath79/generic")
        self.assertEqual(image.source, "fwtool")
        self.assertIn("success", image.extraction_log)
        self.assertIn("[+] fwtool: metadata trailer found", image.extraction_log)
        self.assertEqual(image.fw_version, "23.05.5")
        self.assertEqual(image.compat_version, "1.0")
        self.assertEqual(image.compatible, "tplink,tl-wdr4300-v1")

    @mock.patch(_MOCK_EXTRACTOR)
    @capture_any_output()
    def test_extract_firmware_metadata_dtb_fallback(self, *args):
        MockExtractor = args[0]
        MockExtractor.return_value.extract.return_value = {
            "model": "Xunlong Orange Pi Zero",
            "compatible": ["xunlong,orangepi-zero"],
            "target": "",
            "version": "",
            "compat_version": "1.0",
            "source": "dtb",
        }
        image = self._create_firmware_image()
        FirmwareImage.objects.filter(pk=image.pk).update(
            extraction_status=FirmwareImage.STATUS_UNCONFIRMED
        )
        tasks.extract_firmware_metadata.run(str(image.pk))
        image.refresh_from_db()
        self.assertEqual(image.extraction_status, FirmwareImage.STATUS_INCOMPLETE)
        self.assertEqual(image.source, "dtb")
        self.assertEqual(image.board, "Xunlong Orange Pi Zero")
        self.assertEqual(image.target, "")
        self.assertEqual(image.compatible, "xunlong,orangepi-zero")
        self.assertEqual(image.compat_version, "1.0")
        self.assertIn(
            "[-] fwtool: no metadata trailer found, fell back to DTB scan",
            image.extraction_log,
        )
        self.assertIn(
            "[+] DTB scan: board and compatible extracted", image.extraction_log
        )
        self.assertIn("Manual input is required", image.extraction_log)

    @mock.patch(_MOCK_EXTRACTOR)
    @capture_any_output()
    def test_extract_firmware_metadata_unsupported_error(self, *args):
        MockExtractor = args[0]
        MockExtractor.return_value.extract.side_effect = UnsupportedImageError(
            "armsr image type not supported"
        )
        image = self._create_firmware_image()
        FirmwareImage.objects.filter(pk=image.pk).update(
            extraction_status=FirmwareImage.STATUS_UNCONFIRMED
        )
        tasks.extract_firmware_metadata.run(str(image.pk))
        image.refresh_from_db()
        self.assertEqual(image.extraction_status, FirmwareImage.STATUS_FAILED)
        self.assertEqual(image.failure_reason, FirmwareImage.FAILURE_UNSUPPORTED)
        self.assertIn("Extraction failed", image.extraction_log)

    @mock.patch(_MOCK_EXTRACTOR)
    @capture_any_output()
    def test_extract_firmware_metadata_decompression_limit(self, *args):
        MockExtractor = args[0]
        MockExtractor.return_value.extract.side_effect = DecompressionLimitExceeded(
            "exceeded max decompressed size"
        )
        image = self._create_firmware_image()
        FirmwareImage.objects.filter(pk=image.pk).update(
            extraction_status=FirmwareImage.STATUS_UNCONFIRMED
        )
        tasks.extract_firmware_metadata.run(str(image.pk))
        image.refresh_from_db()
        self.assertEqual(image.extraction_status, FirmwareImage.STATUS_FAILED)
        self.assertEqual(image.failure_reason, FirmwareImage.FAILURE_OOM)

    @mock.patch(_MOCK_EXTRACTOR)
    @capture_any_output()
    def test_extract_firmware_metadata_timeout(self, *args):
        MockExtractor = args[0]
        MockExtractor.return_value.extract.side_effect = SoftTimeLimitExceeded()
        image = self._create_firmware_image()
        FirmwareImage.objects.filter(pk=image.pk).update(
            extraction_status=FirmwareImage.STATUS_UNCONFIRMED
        )
        tasks.extract_firmware_metadata.run(str(image.pk))
        image.refresh_from_db()
        self.assertEqual(image.extraction_status, FirmwareImage.STATUS_FAILED)
        self.assertEqual(image.failure_reason, FirmwareImage.FAILURE_TIMEOUT)

    @mock.patch(_MOCK_EXTRACTOR)
    @capture_any_output()
    def test_extract_firmware_metadata_invalid_exception(self, *args):
        MockExtractor = args[0]
        MockExtractor.return_value.extract.side_effect = RuntimeError("unexpected")
        image = self._create_firmware_image()
        FirmwareImage.objects.filter(pk=image.pk).update(
            extraction_status=FirmwareImage.STATUS_UNCONFIRMED
        )
        tasks.extract_firmware_metadata.run(str(image.pk))
        image.refresh_from_db()
        self.assertEqual(image.extraction_status, FirmwareImage.STATUS_INVALID)
        self.assertEqual(image.failure_reason, FirmwareImage.FAILURE_INVALID)

    @mock.patch("logging.Logger.warning")
    def test_extract_firmware_metadata_image_not_found(self, mock_warning):
        fake_pk = str(uuid.uuid4())
        tasks.extract_firmware_metadata.run(fake_pk)
        mock_warning.assert_called_once()
        self.assertTrue(
            any(fake_pk in str(arg) for arg in mock_warning.call_args.args),
            f"warning should reference the missing image pk {fake_pk}, "
            f"got {mock_warning.call_args.args}",
        )

    @mock.patch(_MOCK_EXTRACTOR)
    def test_extract_firmware_metadata_skips_non_unconfirmed(self, MockExtractor):
        image = self._create_firmware_image()
        FirmwareImage.objects.filter(pk=image.pk).update(
            extraction_status=FirmwareImage.STATUS_IN_PROGRESS
        )
        tasks.extract_firmware_metadata.run(str(image.pk))
        MockExtractor.assert_not_called()
        image.refresh_from_db()
        self.assertEqual(image.extraction_status, FirmwareImage.STATUS_IN_PROGRESS)

    @capture_any_output()
    def test_extract_firmware_metadata_releases_claim_on_concurrent_replace(self):
        image = self._create_firmware_image()
        FirmwareImage.objects.filter(pk=image.pk).update(
            extraction_status=FirmwareImage.STATUS_UNCONFIRMED
        )
        original_get = QuerySet.get

        def flaky_get(self, *args, **kwargs):
            if (
                self.model is FirmwareImage
                and str(kwargs.get("pk")) == str(image.pk)
                and "file" in kwargs
            ):
                # simulate the file being replaced concurrently, after the
                # claim succeeded but before the re-fetch
                FirmwareImage.objects.filter(pk=image.pk).update(
                    file="firmware/replaced.bin"
                )
            return original_get(self, *args, **kwargs)

        with mock.patch.object(QuerySet, "get", flaky_get):
            tasks.extract_firmware_metadata.run(str(image.pk))

        image.refresh_from_db()
        self.assertEqual(image.extraction_status, FirmwareImage.STATUS_UNCONFIRMED)
        self.assertIsNone(image.extraction_claimed_at)

    @mock.patch(_MOCK_NOTIFY)
    @mock.patch(_MOCK_EXTRACTOR)
    @capture_any_output()
    def test_extract_firmware_metadata_failure_sends_notification(self, *args):
        MockExtractor, mock_notify = args[0], args[1]
        MockExtractor.return_value.extract.side_effect = UnsupportedImageError(
            "x86 image type not supported"
        )
        image = self._create_firmware_image()
        FirmwareImage.objects.filter(pk=image.pk).update(
            extraction_status=FirmwareImage.STATUS_UNCONFIRMED
        )
        tasks.extract_firmware_metadata.run(str(image.pk))
        self.assertEqual(mock_notify.call_count, 2)
        call_kwargs = mock_notify.call_args_list[0].kwargs
        self.assertEqual(call_kwargs["level"], "error")
        self.assertIn("#device-metadata", call_kwargs["url"])

    @mock.patch(_MOCK_EXTRACTOR)
    @capture_any_output()
    def test_extract_firmware_metadata_failure_notifies_org_admin(self, *args):
        MockExtractor = args[0]
        MockExtractor.return_value.extract.side_effect = UnsupportedImageError(
            "unsupported image"
        )
        org = self._get_org()
        org_admin = self._create_administrator(organizations=[org])
        superuser = self._get_admin()
        NotificationSetting.objects.filter(
            user=org_admin, organization=org, type="generic_message"
        ).update(web=True, deleted=False)
        image = self._create_firmware_image(organization=org)
        FirmwareImage.objects.filter(pk=image.pk).update(
            extraction_status=FirmwareImage.STATUS_UNCONFIRMED
        )
        tasks.extract_firmware_metadata.run(str(image.pk))

        with self.subTest("org admin is notified"):
            self.assertTrue(
                Notification.objects.filter(
                    recipient=org_admin, type="generic_message"
                ).exists()
            )

        with self.subTest("superuser is still notified"):
            self.assertTrue(
                Notification.objects.filter(
                    recipient=superuser, type="generic_message"
                ).exists()
            )

    @mock.patch(_MOCK_NOTIFY)
    @mock.patch(_MOCK_EXTRACTOR)
    @capture_any_output()
    def test_extract_firmware_metadata_invalid_sends_notifications(self, *args):
        MockExtractor, mock_notify = args[0], args[1]
        MockExtractor.return_value.extract.side_effect = RuntimeError("unexpected")
        image = self._create_firmware_image()
        FirmwareImage.objects.filter(pk=image.pk).update(
            extraction_status=FirmwareImage.STATUS_UNCONFIRMED
        )
        tasks.extract_firmware_metadata.run(str(image.pk))
        mock_notify.assert_called()
        call_kwargs = mock_notify.call_args_list[0].kwargs
        self.assertEqual(call_kwargs["level"], "error")
        self.assertIn("#device-metadata", call_kwargs["url"])

    @mock.patch(_MOCK_NOTIFY)
    @mock.patch(_MOCK_EXTRACTOR)
    @capture_any_output()
    def test_extract_firmware_metadata_dtb_sends_notification(self, *args):
        MockExtractor, mock_notify = args[0], args[1]
        MockExtractor.return_value.extract.return_value = {
            "model": "Xunlong Orange Pi Zero",
            "compatible": ["xunlong,orangepi-zero"],
            "target": "",
            "version": "",
            "compat_version": "1.0",
            "source": "dtb",
        }
        image = self._create_firmware_image()
        FirmwareImage.objects.filter(pk=image.pk).update(
            extraction_status=FirmwareImage.STATUS_UNCONFIRMED
        )
        tasks.extract_firmware_metadata.run(str(image.pk))
        self.assertEqual(mock_notify.call_count, 2)
        call_kwargs = mock_notify.call_args_list[0].kwargs
        self.assertEqual(call_kwargs["level"], "warning")
        self.assertIn("#device-metadata", call_kwargs["url"])

    @mock.patch(_MOCK_NOTIFY)
    @mock.patch(_MOCK_EXTRACTOR)
    @capture_any_output()
    def test_extract_firmware_metadata_fwtool_success_no_dtb_notification(self, *args):
        MockExtractor, mock_notify = args[0], args[1]
        MockExtractor.return_value.extract.return_value = {
            "model": "TP-Link WDR4300",
            "compatible": ["tplink,tl-wdr4300-v1"],
            "target": "ath79/generic",
            "version": "23.05.5",
            "compat_version": "1.0",
            "source": "fwtool",
        }
        image = self._create_firmware_image()
        FirmwareImage.objects.filter(pk=image.pk).update(
            extraction_status=FirmwareImage.STATUS_UNCONFIRMED
        )
        tasks.extract_firmware_metadata.run(str(image.pk))
        mock_notify.assert_called_once()
        call_kwargs = mock_notify.call_args.kwargs
        self.assertEqual(call_kwargs["level"], "info")
        self.assertNotIn("#device-metadata", call_kwargs["url"])

    @mock.patch(_MOCK_EXTRACTOR)
    @capture_any_output()
    def test_extract_firmware_metadata_fwtool_success_without_model(self, *args):
        MockExtractor = args[0]
        MockExtractor.return_value.extract.return_value = {
            "model": "",
            "compatible": ["tplink,tl-wdr4300-v1"],
            "target": "ath79/generic",
            "version": "23.05.5",
            "compat_version": "1.0",
            "source": "fwtool",
        }
        image = self._create_firmware_image()
        FirmwareImage.objects.filter(pk=image.pk).update(
            extraction_status=FirmwareImage.STATUS_UNCONFIRMED
        )
        tasks.extract_firmware_metadata.run(str(image.pk))
        image.refresh_from_db()
        self.assertEqual(image.extraction_status, FirmwareImage.STATUS_FAILED)
        self.assertEqual(image.board, "")
        self.assertEqual(image.target, "ath79/generic")
        self.assertEqual(image.fw_version, "23.05.5")
        self.assertEqual(image.source, "fwtool")

    @mock.patch(_MOCK_EXTRACTOR)
    @capture_any_output()
    def test_extract_firmware_metadata_dtb_success_without_model(self, *args):
        MockExtractor = args[0]
        MockExtractor.return_value.extract.return_value = {
            "model": None,
            "compatible": ["xunlong,orangepi-zero"],
            "target": "",
            "version": "",
            "compat_version": "1.0",
            "source": "dtb",
        }
        image = self._create_firmware_image()
        FirmwareImage.objects.filter(pk=image.pk).update(
            extraction_status=FirmwareImage.STATUS_UNCONFIRMED
        )
        tasks.extract_firmware_metadata.run(str(image.pk))
        image.refresh_from_db()
        self.assertEqual(image.extraction_status, FirmwareImage.STATUS_FAILED)
        self.assertEqual(image.board, "")
        self.assertEqual(image.compatible, "xunlong,orangepi-zero")
        self.assertEqual(image.source, "dtb")

    def test_compat_blocks_pairing_above_1_0(self):
        self.assertTrue(utils.compat_blocks_pairing("1.1"))
        self.assertTrue(utils.compat_blocks_pairing("2.0"))

    def test_compat_blocks_pairing_at_or_below_1_0(self):
        self.assertFalse(utils.compat_blocks_pairing("1.0"))
        self.assertFalse(tasks.compat_blocks_pairing("0.9"))

    def test_compat_blocks_pairing_invalid_values(self):
        self.assertFalse(utils.compat_blocks_pairing(""))
        self.assertFalse(utils.compat_blocks_pairing(None))
        self.assertFalse(utils.compat_blocks_pairing("bad"))

    @mock.patch(
        "openwisp_firmware_upgrader.base.models.AbstractDeviceFirmware.create_for_device"
    )
    @capture_any_output()
    def test_create_all_device_firmwares_skips_pairing_for_high_compat(
        self, mock_create_for_device
    ):
        Build = load_model("Build")
        image = self._create_firmware_image()
        Build.objects.filter(pk=image.build.pk).update(os="OpenWrt 23.05.5")
        self._create_device(
            os="OpenWrt 23.05.5",
            organization=image.build.category.organization,
            model=image.board,
        )
        FirmwareImage.objects.filter(pk=image.pk).update(compat_version="2.0")
        tasks.create_all_device_firmwares.run(str(image.pk))
        mock_create_for_device.assert_not_called()

    @mock.patch(
        "openwisp_firmware_upgrader.base.models.AbstractDeviceFirmware.create_for_device"
    )
    @capture_any_output()
    def test_create_all_device_firmwares_filters_by_organization(
        self, mock_create_for_device
    ):
        Build = load_model("Build")
        image = self._create_firmware_image()
        Build.objects.filter(pk=image.build.pk).update(os="OpenWrt 23.05.5")
        same_org_device = self._create_device(
            os="OpenWrt 23.05.5",
            organization=image.build.category.organization,
            model=image.board,
        )
        other_org = self._create_org(name="other-org", slug="other-org")
        other_org_device = self._create_device(
            os="OpenWrt 23.05.5",
            organization=other_org,
            model=image.board,
        )
        tasks.create_all_device_firmwares.run(str(image.pk))
        called_devices = [
            call.args[0] for call in mock_create_for_device.call_args_list
        ]
        self.assertIn(same_org_device, called_devices)
        self.assertNotIn(other_org_device, called_devices)

    @mock.patch(
        "openwisp_firmware_upgrader.base.models.AbstractDeviceFirmware.create_for_device"
    )
    @capture_any_output()
    def test_create_all_device_firmwares_shared_image_pairs_all_orgs(
        self, mock_create_for_device
    ):
        Build = load_model("Build")
        image = self._create_firmware_image(organization=None)
        Build.objects.filter(pk=image.build.pk).update(os="OpenWrt 23.05.5")
        org1 = self._get_org()
        org1_device = self._create_device(
            os="OpenWrt 23.05.5", organization=org1, model=image.board
        )
        org2 = self._create_org(name="org2", slug="org2")
        org2_device = self._create_device(
            os="OpenWrt 23.05.5", organization=org2, model=image.board
        )
        tasks.create_all_device_firmwares.run(str(image.pk))
        called_devices = [
            call.args[0] for call in mock_create_for_device.call_args_list
        ]
        self.assertIn(org1_device, called_devices)
        self.assertIn(org2_device, called_devices)

    @mock.patch(_MOCK_EXTRACTOR)
    @mock.patch("openwisp_firmware_upgrader.tasks.create_all_device_firmwares")
    @capture_any_output()
    def test_extract_firmware_metadata_triggers_pairing_for_low_compat(
        self, mock_create_firmwares, MockExtractor
    ):
        MockExtractor.return_value.extract.return_value = {
            "model": "Test Device",
            "compatible": ["test,device"],
            "target": "test/target",
            "version": "23.05.5",
            "compat_version": "1.0",
            "source": "fwtool",
        }
        image = self._create_firmware_image()
        FirmwareImage.objects.filter(pk=image.pk).update(
            extraction_status=FirmwareImage.STATUS_UNCONFIRMED
        )
        tasks.extract_firmware_metadata.run(str(image.pk))
        mock_create_firmwares.delay.assert_called_once_with(str(image.pk))

    @mock.patch(
        "openwisp_firmware_upgrader.tasks._dispatch_unconfirmed_extractions_chunk.delay"
    )
    def test_queue_unconfirmed_extractions_dispatch_in_chunks(self, mock_delay):
        image1 = self._create_firmware_image()
        image2 = self._create_firmware_image(build=self._create_build(version="0.2"))
        image3 = self._create_firmware_image(build=self._create_build(version="0.3"))
        FirmwareImage.objects.filter(pk__in=[image1.pk, image2.pk, image3.pk]).update(
            extraction_status=FirmwareImage.STATUS_UNCONFIRMED
        )
        with mock.patch.object(app_settings, "QUEUE_UNCONFIRMED_CHUNK_SIZE", 2):
            tasks.queue_unconfirmed_extractions.run()
        self.assertEqual(mock_delay.call_count, 2)
        dispatched_pks = [
            pk for call in mock_delay.call_args_list for pk in call.args[0]
        ]
        self.assertEqual(set(dispatched_pks), {image1.pk, image2.pk, image3.pk})
        self.assertEqual(len(dispatched_pks), 3)
        chunk_size = sorted(len(call.args[0]) for call in mock_delay.call_args_list)
        self.assertEqual(chunk_size, [1, 2])

    @mock.patch(_MOCK_EXTRACTOR)
    @mock.patch("openwisp_firmware_upgrader.tasks.create_all_device_firmwares")
    @capture_any_output()
    def test_extract_firmware_metadata_dtb_incomplete_does_not_trigger_pairing(
        self, mock_create_firmwares, MockExtractor
    ):
        MockExtractor.return_value.extract.return_value = {
            "model": "Xunlong Orange Pi Zero",
            "compatible": ["xunlong,orangepi-zero"],
            "target": "",
            "version": "",
            "compat_version": "1.0",
            "source": "dtb",
        }
        image = self._create_firmware_image()
        FirmwareImage.objects.filter(pk=image.pk).update(
            extraction_status=FirmwareImage.STATUS_UNCONFIRMED
        )
        tasks.extract_firmware_metadata.run(str(image.pk))
        image.refresh_from_db()
        self.assertEqual(image.extraction_status, FirmwareImage.STATUS_INCOMPLETE)
        mock_create_firmwares.delay.assert_not_called()

    @capture_any_output()
    def test_extract_firmware_metadata_persist_failure_notifies_and_publishes(self):
        image = self._create_firmware_image()
        FirmwareImage.objects.filter(pk=image.pk).update(
            extraction_status=FirmwareImage.STATUS_UNCONFIRMED
        )
        original_update = QuerySet.update

        def flaky_update(self, *args, **kwargs):
            if self.model is FirmwareImage and "board" in kwargs:
                raise Exception("simulated persist failure")
            return original_update(self, *args, **kwargs)

        with mock.patch(_MOCK_EXTRACTOR) as MockExtractor, mock.patch.object(
            QuerySet, "update", flaky_update
        ), mock.patch(
            "openwisp_firmware_upgrader.tasks.FirmwareExtractionPublisher"
        ) as MockPublisher, mock.patch(
            _MOCK_NOTIFY
        ) as mock_notify:
            MockExtractor.return_value.extract.return_value = {
                "model": "TP-Link WDR4300",
                "compatible": ["tplink,tl-wdr4300-v1"],
                "target": "ath79/generic",
                "version": "23.05.5",
                "compat_version": "1.0",
                "source": "fwtool",
            }
            tasks.extract_firmware_metadata.run(str(image.pk))

        image.refresh_from_db()
        self.assertEqual(image.extraction_status, FirmwareImage.STATUS_INVALID)
        self.assertEqual(image.failure_reason, FirmwareImage.FAILURE_INVALID)
        self.assertTrue(image.extraction_log)
        MockPublisher.return_value.publish_status.assert_called_once_with(
            FirmwareImage.STATUS_INVALID
        )
        mock_notify.assert_called_once()
        self.assertEqual(mock_notify.call_args.kwargs["level"], "error")

    @capture_any_output()
    def test_reclaim_stale_extractions_recovers_stuck_image(self):
        image = self._create_firmware_image()
        stale_claim = timezone.now() - timedelta(
            seconds=app_settings.EXTRACTION_CLAIM_TIMEOUT + 60
        )
        FirmwareImage.objects.filter(pk=image.pk).update(
            extraction_status=FirmwareImage.STATUS_IN_PROGRESS,
            extraction_claimed_at=stale_claim,
        )
        with mock.patch(
            "openwisp_firmware_upgrader.tasks.FirmwareExtractionPublisher"
        ) as MockPublisher, mock.patch(_MOCK_NOTIFY) as mock_notify:
            tasks.reclaim_stale_extractions.run()

        image.refresh_from_db()
        self.assertEqual(image.extraction_status, FirmwareImage.STATUS_FAILED)
        self.assertEqual(image.failure_reason, FirmwareImage.FAILURE_TIMEOUT)
        self.assertTrue(image.extraction_log)
        MockPublisher.return_value.publish_status.assert_called_once_with(
            FirmwareImage.STATUS_FAILED
        )
        self.assertEqual(mock_notify.call_count, 2)
        call_kwargs = mock_notify.call_args_list[0].kwargs
        self.assertEqual(call_kwargs["level"], "error")
        image.build.refresh_from_db()
        self.assertEqual(image.build.status, image.build.BUILD_STATUS_FAILED)

    @capture_any_output()
    def test_reclaim_stale_extractions_ignores_fresh_claim(self):
        image = self._create_firmware_image()
        FirmwareImage.objects.filter(pk=image.pk).update(
            extraction_status=FirmwareImage.STATUS_IN_PROGRESS,
            extraction_claimed_at=timezone.now(),
        )
        tasks.reclaim_stale_extractions.run()
        image.refresh_from_db()
        self.assertEqual(image.extraction_status, FirmwareImage.STATUS_IN_PROGRESS)

    @capture_any_output()
    def test_reclaim_stale_extractions_ignores_non_in_progress_images(self):
        image = self._create_firmware_image()
        stale_claim = timezone.now() - timedelta(
            seconds=app_settings.EXTRACTION_CLAIM_TIMEOUT + 60
        )
        FirmwareImage.objects.filter(pk=image.pk).update(
            extraction_status=FirmwareImage.STATUS_UNCONFIRMED,
            extraction_claimed_at=stale_claim,
        )
        tasks.reclaim_stale_extractions.run()
        image.refresh_from_db()
        self.assertEqual(image.extraction_status, FirmwareImage.STATUS_UNCONFIRMED)

    @capture_any_output()
    def test_reclaim_stale_extractions_reclaims_null_claimed_at(self):
        image = self._create_firmware_image()
        FirmwareImage.objects.filter(pk=image.pk).update(
            extraction_status=FirmwareImage.STATUS_IN_PROGRESS,
            extraction_claimed_at=None,
        )
        tasks.reclaim_stale_extractions.run()
        image.refresh_from_db()
        self.assertEqual(image.extraction_status, FirmwareImage.STATUS_FAILED)
        self.assertEqual(image.failure_reason, FirmwareImage.FAILURE_TIMEOUT)
