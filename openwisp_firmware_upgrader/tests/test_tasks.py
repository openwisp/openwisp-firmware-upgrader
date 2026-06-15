import uuid
from unittest import mock

from celery.exceptions import SoftTimeLimitExceeded
from django.test import TransactionTestCase

from openwisp_utils.tests import capture_any_output

from .. import tasks
from ..extractors.exceptions import DecompressionLimitExceeded, UnsupportedImageError
from ..swapper import load_model
from .base import TestUpgraderMixin

BatchUpgradeOperation = load_model("BatchUpgradeOperation")
FirmwareImage = load_model("FirmwareImage")
UpgradeOperation = load_model("UpgradeOperation")

_MOCK_EXTRACTOR = "openwisp_firmware_upgrader.tasks.OpenWrtMetadataExtractor"


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
        batch_id = BatchUpgradeOperation().id
        tasks.batch_upgrade_operation.run(batch_id=batch_id, firmwareless=False)
        mocked_logger.assert_called_with(
            f"The BatchUpgradeOperation object with id {batch_id} has been deleted"
        )

    @mock.patch(_MOCK_EXTRACTOR)
    @capture_any_output()
    def test_extract_firmware_metadata_success(self, *args):
        MockExtractor = args[0]
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
        self.assertEqual(image.fw_version, "23.05.5")
        self.assertEqual(image.compat_version, "1.0")
        self.assertEqual(image.compatible, ["tplink,tl-wdr4300-v1"])

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
        self.assertEqual(image.extraction_status, FirmwareImage.STATUS_SUCCESS)
        self.assertEqual(image.source, "dtb")
        self.assertEqual(image.board, "Xunlong Orange Pi Zero")
        self.assertEqual(image.target, "")
        self.assertEqual(image.compatible, ["xunlong,orangepi-zero"])
        self.assertEqual(image.compat_version, "1.0")

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
        self.assertTrue(any(fake_pk in str(arg) for arg in mock_warning.call_args.args))

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

    def test_compat_blocks_pairing_above_1_0(self):
        self.assertTrue(tasks._compat_blocks_pairing("1.1"))
        self.assertTrue(tasks._compat_blocks_pairing("2.0"))

    def test_compat_blocks_pairing_at_or_below_1_0(self):
        self.assertFalse(tasks._compat_blocks_pairing("1.0"))
        self.assertFalse(tasks._compat_blocks_pairing("0.9"))

    def test_compat_blocks_pairing_invalid_values(self):
        self.assertFalse(tasks._compat_blocks_pairing(""))
        self.assertFalse(tasks._compat_blocks_pairing(None))
        self.assertFalse(tasks._compat_blocks_pairing("bad"))

    @mock.patch(_MOCK_EXTRACTOR)
    @mock.patch("openwisp_firmware_upgrader.tasks.create_all_device_firmwares")
    @capture_any_output()
    def test_extract_firmware_metadata_skips_pairing_for_high_compat(
        self, mock_create_firmwares, MockExtractor
    ):
        MockExtractor.return_value.extract.return_value = {
            "model": "Test Device",
            "compatible": ["test,device"],
            "target": "test/target",
            "version": "23.05.5",
            "compat_version": "2.0",
            "source": "fwtool",
        }
        image = self._create_firmware_image()
        FirmwareImage.objects.filter(pk=image.pk).update(
            extraction_status=FirmwareImage.STATUS_UNCONFIRMED
        )
        tasks.extract_firmware_metadata.run(str(image.pk))
        mock_create_firmwares.delay.assert_not_called()

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
