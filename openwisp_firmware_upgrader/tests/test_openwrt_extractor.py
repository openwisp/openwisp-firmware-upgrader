import bz2
import gzip
import json
import lzma
import os
import struct
import tempfile
from unittest import mock

from django.test import TestCase

from ..extractors.exceptions import (
    DecompressionLimitExceeded,
    ExtractionError,
    UnsupportedImageError,
)
from ..extractors.openwrt import (
    DTB_MAGIC,
    DTB_MIN_SIZE,
    FWIMAGE_INFO,
    FWIMAGE_MAGIC,
    HEADER_SIZE,
    TRAILER_FORMAT,
    TRAILER_SIZE,
    UIMAGE_HEADER_SIZE,
    UIMAGE_MAGIC,
    OpenWrtMetadataExtractor,
    _check_limits,
    _crc32_block,
    _decompress,
    _extract_fwtool_metadata,
    _locate_dtb,
    _parse_supported_devices,
    _strip_uimage_header,
    _try_bz2,
    _try_gzip,
    _try_lzma,
    _try_xz,
)
from ..upgraders.openwrt import OpenWrt


class TestParseSupportedDevices(TestCase):
    def test_compat_version_1_returns_supported_devices(self):
        meta = {
            "compat_version": "1.0",
            "supported_devices": ["tplink,tl-wdr4300-v1"],
            "new_supported_devices": ["tplink,tl-wdr4300-v1-new"],
        }
        self.assertEqual(_parse_supported_devices(meta), ["tplink,tl-wdr4300-v1"])

    def test_compat_version_not_1_returns_new_supported_devices(self):
        meta = {
            "compat_version": "2.0",
            "supported_devices": ["tplink,tl-wdr4300-v1"],
            "new_supported_devices": ["tplink,tl-wdr4300-v1-new"],
        }
        self.assertEqual(_parse_supported_devices(meta), ["tplink,tl-wdr4300-v1-new"])

    def test_missing_compat_version_defaults_to_1(self):
        meta = {"supported_devices": ["tplink,tl-wdr4300-v1"]}
        self.assertEqual(_parse_supported_devices(meta), ["tplink,tl-wdr4300-v1"])


class TestDetectImageType(TestCase):
    def test_x86_img_raises_unsupported(self):
        extractor = OpenWrtMetadataExtractor("/path/to/image.img")
        with self.assertRaises(UnsupportedImageError):
            extractor._detect_image_type()

    def test_vmdk_raises_unsupported(self):
        extractor = OpenWrtMetadataExtractor("/path/to/image.vmdk")
        with self.assertRaises(UnsupportedImageError):
            extractor._detect_image_type()

    def test_vdi_raises_unsupported(self):
        extractor = OpenWrtMetadataExtractor("/path/to/image.vdi")
        with self.assertRaises(UnsupportedImageError):
            extractor._detect_image_type()

    def test_armsr_raises_unsupported(self):
        extractor = OpenWrtMetadataExtractor("/path/to/armsr-image.bin")
        with self.assertRaises(UnsupportedImageError):
            extractor._detect_image_type()

    def test_sysupgrade_passes(self):
        extractor = OpenWrtMetadataExtractor(
            "/path/to/ath79-generic-tplink_tl-wdr4300-v1-squashfs-sysupgrade.bin"
        )
        extractor._detect_image_type()  # must not raise


class TestExtractFromImage(TestCase):
    _PATH = "/path/to/ath79-generic-tplink_tl-wdr4300-v1-squashfs-sysupgrade.bin"
    _MOCK = "openwisp_firmware_upgrader.extractors.openwrt._extract_fwtool_metadata"

    def _mock_fwtool(self, meta_dict):
        extractor = OpenWrtMetadataExtractor(self._PATH)
        with mock.patch(self._MOCK, return_value=meta_dict):
            return extractor.extract_from_image()

    def test_happy_path(self):
        meta = {
            "version": {
                "board": "tplink,tl-wdr4300-v1",
                "target": "ath79/generic",
                "version": "SNAPSHOT",
            },
            "compat_version": "1.0",
            "supported_devices": ["tplink,tl-wdr4300-v1"],
        }
        result = self._mock_fwtool(meta)
        self.assertEqual(result["model"], "tplink,tl-wdr4300-v1")
        self.assertEqual(result["target"], "ath79/generic")
        self.assertEqual(result["version"], "SNAPSHOT")
        self.assertEqual(result["source"], "fwtool")

    def test_none_meta_raises_extraction_error(self):
        extractor = OpenWrtMetadataExtractor(self._PATH)
        with mock.patch(self._MOCK, return_value=None):
            with self.assertRaises(ExtractionError):
                extractor.extract_from_image()

    def test_dsa_migration_compat_v2(self):
        meta = {
            "version": {"board": "x", "target": "x", "version": "x"},
            "compat_version": "2.0",
            "new_supported_devices": ["tplink,tl-wdr4300-v1-new"],
            "supported_devices": ["tplink,tl-wdr4300-v1"],
        }
        result = self._mock_fwtool(meta)
        self.assertIn("tplink,tl-wdr4300-v1-new", result["compatible"])
        self.assertNotIn("tplink,tl-wdr4300-v1", result["compatible"])


class TestUpgraderSeam(TestCase):
    def test_metadata_extractor_class_is_openwrt_extractor(self):
        self.assertIs(OpenWrt.metadata_extractor_class, OpenWrtMetadataExtractor)


class TestCheckLimits(TestCase):
    def test_size_within_limit(self):
        with mock.patch(
            "openwisp_firmware_upgrader.settings.MAX_DECOMPRESSED_BYTES", 200
        ):
            _check_limits(100, 100)  # must not raise

    def test_hard_limit_exceeded_raises(self):
        with mock.patch(
            "openwisp_firmware_upgrader.settings.MAX_DECOMPRESSED_BYTES", 200
        ):
            with self.assertRaises(DecompressionLimitExceeded):
                _check_limits(300, 100)

    def test_ratio_exceeded_raises(self):
        with mock.patch(
            "openwisp_firmware_upgrader.settings.MAX_DECOMPRESSED_RATIO", 10
        ):
            with self.assertRaises(DecompressionLimitExceeded):
                _check_limits(1100, 100)


class TestStripUimageHeader(TestCase):
    def test_strips_64_byte_header_when_magic_matches(self):
        payload = b"kernel_data_here" * 10
        header = bytearray(UIMAGE_HEADER_SIZE)
        header[:4] = UIMAGE_MAGIC
        struct.pack_into(">I", header, 12, len(payload))
        data = bytes(header) + payload
        result = _strip_uimage_header(data)
        self.assertEqual(result, payload)

    def test_passthrough_when_magic_does_not_match(self):
        data = b"\x00\x01\x02\x03" + b"x" * 100
        result = _strip_uimage_header(data)
        self.assertEqual(result, data)

    def test_passthrough_when_data_shorter_than_header(self):
        data = UIMAGE_MAGIC + b"\x00" * 10
        result = _strip_uimage_header(data)
        self.assertEqual(result, data)


class TestLocateDtb(TestCase):
    def test_returns_none_when_no_dtb_magic(self):
        kernel = b"\xde\xad\xbe\xef" * 50
        self.assertIsNone(_locate_dtb(kernel))

    def test_returns_none_when_candidate_size_below_minimum(self):
        bad_dtb = DTB_MAGIC + struct.pack(">I", DTB_MIN_SIZE - 1) + b"\x00" * 60
        self.assertIsNone(_locate_dtb(b"\x00" * 100 + bad_dtb))


class TestIndividualDecompressors(TestCase):
    def test_try_gzip_decompresses(self):
        original = b"Hello OpenWrt gzip"
        result = _try_gzip(gzip.compress(original))
        self.assertEqual(result, original)

    def test_try_gzip_returns_none_for_wrong_magic(self):
        self.assertIsNone(_try_gzip(b"\x00" * 20))

    def test_try_xz_decompresses(self):
        original = b"Hello OpenWrt xz"
        compressed = lzma.compress(original, format=lzma.FORMAT_XZ)
        result = _try_xz(compressed)
        self.assertEqual(result, original)

    def test_try_xz_returns_none_for_wrong_magic(self):
        self.assertIsNone(_try_xz(b"\x00" * 20))

    def test_try_lzma_decompresses(self):
        original = b"Hello OpenWrt lzma"
        compressed = lzma.compress(original, format=lzma.FORMAT_ALONE)
        result = _try_lzma(compressed)
        self.assertEqual(result, original)

    def test_try_lzma_returns_none_for_wrong_magic(self):
        self.assertIsNone(_try_lzma(b"\x00" * 20))

    def test_try_bz2_decompresses(self):
        original = b"Hello OpenWrt bz2"
        result = _try_bz2(bz2.compress(original))
        self.assertEqual(result, original)

    def test_try_bz2_returns_none_for_wrong_magic(self):
        self.assertIsNone(_try_bz2(b"\x00" * 20))


class TestDecompress(TestCase):
    def test_gzip_decompressed(self):
        original = b"Hello OpenWrt firmware!"
        result = _decompress(gzip.compress(original))
        self.assertEqual(result, original)

    def test_xz_decompressed(self):
        original = b"Hello OpenWrt firmware!"
        result = _decompress(lzma.compress(original, format=lzma.FORMAT_XZ))
        self.assertEqual(result, original)

    def test_bz2_decompressed(self):
        original = b"Hello OpenWrt firmware!"
        result = _decompress(bz2.compress(original))
        self.assertEqual(result, original)

    def test_lzma_decompressed(self):
        original = b"Hello OpenWrt firmware!"
        result = _decompress(lzma.compress(original, format=lzma.FORMAT_ALONE))
        self.assertEqual(result, original)

    def test_unrecognised_format_returned_as_is(self):
        data = b"\x00\x01\x02\x03" * 10
        result = _decompress(data)
        self.assertEqual(result, data)


class TestExtractOverride(TestCase):
    _PATH = "/path/to/ath79-generic-tplink_tl-wdr4300-v1-squashfs-sysupgrade.bin"

    def _make_extractor(self, path=None):
        return OpenWrtMetadataExtractor(path or self._PATH)

    def test_fwtool_success_returns_fwtool_result(self):
        extractor = self._make_extractor()
        fwtool_result = {
            "model": "x",
            "compatible": ["x"],
            "target": "x",
            "version": "x",
            "compat_version": "1.0",
            "source": "fwtool",
        }
        with mock.patch.object(
            extractor, "extract_from_image", return_value=fwtool_result
        ):
            result = extractor.extract()
        self.assertEqual(result["source"], "fwtool")

    def test_fwtool_failure_falls_back_to_dtb(self):
        extractor = self._make_extractor()
        dtb_result = {
            "model": "dtb-model",
            "compatible": ["dtb,compat"],
            "target": "",
            "version": "",
            "compat_version": "1.0",
            "source": "dtb",
        }
        with mock.patch.object(
            extractor, "extract_from_image", side_effect=ExtractionError("fail")
        ):
            with mock.patch.object(
                extractor, "extract_from_dtb", return_value=dtb_result
            ):
                result = extractor.extract()
        self.assertEqual(result["source"], "dtb")

    def test_both_paths_fail_raises(self):
        extractor = self._make_extractor()
        with mock.patch.object(
            extractor, "extract_from_image", side_effect=ExtractionError("fail")
        ):
            with mock.patch.object(
                extractor,
                "extract_from_dtb",
                side_effect=UnsupportedImageError("no dtb"),
            ):
                with self.assertRaises(UnsupportedImageError):
                    extractor.extract()

    def test_dtb_enriches_missing_compatible(self):
        extractor = self._make_extractor()
        fwtool_result = {
            "model": "x",
            "compatible": [],
            "target": "x",
            "version": "x",
            "compat_version": "1.0",
            "source": "fwtool",
        }
        dtb_result = {
            "model": "",
            "compatible": ["enriched,compat"],
            "target": "",
            "version": "",
            "compat_version": "1.0",
            "source": "dtb",
        }
        with mock.patch.object(
            extractor, "extract_from_image", return_value=fwtool_result
        ):
            with mock.patch.object(
                extractor, "extract_from_dtb", return_value=dtb_result
            ):
                result = extractor.extract()
        self.assertIn("enriched,compat", result["compatible"])
        self.assertEqual(result["source"], "fwtool")

    def test_unsupported_image_error_propagates_without_dtb_attempt(self):
        extractor = self._make_extractor("/path/to/image.img")
        with mock.patch.object(extractor, "extract_from_dtb") as mock_dtb:
            with self.assertRaises(UnsupportedImageError):
                extractor.extract()
        mock_dtb.assert_not_called()


class TestExtractFwtoolMetadata(TestCase):
    def _build_image(self, meta_dict, prefix=b"\x00" * 32):
        json_bytes = json.dumps(meta_dict).encode("utf-8")
        header = b"\x00" * HEADER_SIZE
        data_block = prefix + header + json_bytes
        size = HEADER_SIZE + len(json_bytes) + TRAILER_SIZE
        crc = _crc32_block(0xFFFFFFFF, data_block)
        trailer = struct.pack(
            TRAILER_FORMAT, FWIMAGE_MAGIC, crc, FWIMAGE_INFO, b"\x00\x00\x00", size
        )
        return data_block + trailer

    def _write_image(self, data):
        f = tempfile.NamedTemporaryFile(suffix=".bin", delete=False)
        f.write(data)
        f.close()
        return f.name

    def test_extracts_metadata_from_valid_trailer(self):
        meta = {
            "version": {
                "board": "tplink,tl-wdr4300-v1",
                "target": "ath79/generic",
                "version": "SNAPSHOT",
            },
            "compat_version": "1.0",
            "supported_devices": ["tplink,tl-wdr4300-v1"],
        }
        path = self._write_image(self._build_image(meta))
        try:
            result = _extract_fwtool_metadata(path)
        finally:
            os.unlink(path)
        self.assertIsNotNone(result)
        self.assertEqual(result["version"]["board"], "tplink,tl-wdr4300-v1")
        self.assertEqual(result["compat_version"], "1.0")

    def test_returns_none_when_no_trailer(self):
        path = self._write_image(b"\x00" * 256)
        try:
            result = _extract_fwtool_metadata(path)
        finally:
            os.unlink(path)
        self.assertIsNone(result)

    def test_returns_none_on_corrupt_crc(self):
        meta = {"version": {"board": "x", "target": "x", "version": "x"}}
        image = bytearray(self._build_image(meta))
        # Flip a byte in the CRC field (bytes 4-7 of the trailer)
        image[-TRAILER_SIZE + 4] ^= 0xFF
        path = self._write_image(bytes(image))
        try:
            result = _extract_fwtool_metadata(path)
        finally:
            os.unlink(path)
        self.assertIsNone(result)
