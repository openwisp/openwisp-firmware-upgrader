import bz2
import gzip
import hashlib
import json
import lzma
import os
import struct
import tempfile
import urllib.request
from pathlib import Path
from unittest import mock

import lz4.frame as lz4frame
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
)
from ..upgraders.openwrt import OpenWrt

_CHECKSUMS_FILE = Path(__file__).parent / "fixtures" / "firmware_checksums.json"
_CACHE_DIR = Path(__file__).parent / ".firmware_cache"


def _get_firmware(key):
    with open(_CHECKSUMS_FILE) as f:
        entry = json.load(f)[key]
    _CACHE_DIR.mkdir(exist_ok=True)
    cached = _CACHE_DIR / entry["url"].split("/")[-1]
    if cached.exists():
        with open(cached, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        if digest == entry["sha256"]:
            return cached
        cached.unlink()
    try:
        urllib.request.urlretrieve(entry["url"], cached)
    except Exception:
        return None
    with open(cached, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    if digest != entry["sha256"]:
        cached.unlink()
        return None
    return cached


class TestParseSupportedDevices(TestCase):
    def setUp(self):
        self.extractor = OpenWrtMetadataExtractor(
            "/path/to/ath79-generic-tplink_tl-wdr4300-v1-squashfs-sysupgrade.bin"
        )

    def test_compat_version_1_returns_supported_devices(self):
        meta = {
            "compat_version": "1.0",
            "supported_devices": ["tplink,tl-wdr4300-v1"],
            "new_supported_devices": ["tplink,tl-wdr4300-v1-new"],
        }
        self.assertEqual(
            self.extractor._parse_supported_devices(meta), ["tplink,tl-wdr4300-v1"]
        )

    def test_compat_version_not_1_returns_new_supported_devices(self):
        meta = {
            "compat_version": "2.0",
            "supported_devices": ["tplink,tl-wdr4300-v1"],
            "new_supported_devices": ["tplink,tl-wdr4300-v1-new"],
        }
        self.assertEqual(
            self.extractor._parse_supported_devices(meta), ["tplink,tl-wdr4300-v1-new"]
        )

    def test_missing_compat_version_defaults_to_1(self):
        meta = {"supported_devices": ["tplink,tl-wdr4300-v1"]}
        self.assertEqual(
            self.extractor._parse_supported_devices(meta), ["tplink,tl-wdr4300-v1"]
        )


class TestDetectImageType(TestCase):
    def test_x86_img_raises_unsupported(self):
        extractor = OpenWrtMetadataExtractor(
            "/path/to/openwrt-x86-64-generic-ext4-combined.img"
        )
        with self.assertRaises(UnsupportedImageError):
            extractor._validate_image_type()

    def test_vmdk_raises_unsupported(self):
        extractor = OpenWrtMetadataExtractor("/path/to/image.vmdk")
        with self.assertRaises(UnsupportedImageError):
            extractor._validate_image_type()

    def test_vdi_raises_unsupported(self):
        extractor = OpenWrtMetadataExtractor("/path/to/image.vdi")
        with self.assertRaises(UnsupportedImageError):
            extractor._validate_image_type()

    def test_armsr_raises_unsupported(self):
        extractor = OpenWrtMetadataExtractor("/path/to/armsr-image.bin")
        with self.assertRaises(UnsupportedImageError):
            extractor._validate_image_type()

    def test_sysupgrade_passes(self):
        extractor = OpenWrtMetadataExtractor(
            "/path/to/ath79-generic-tplink_tl-wdr4300-v1-squashfs-sysupgrade.bin"
        )
        extractor._validate_image_type()  # must not raise

    def test_sdcard_img_passes(self):
        extractor = OpenWrtMetadataExtractor(
            "/path/to/openwrt-sunxi-cortexa7-xunlong_orangepi-zero-ext4-sdcard.img"
        )
        extractor._validate_image_type()  # must not raise


class TestExtractFromImage(TestCase):
    _PATH = "/path/to/ath79-generic-tplink_tl-wdr4300-v1-squashfs-sysupgrade.bin"

    def _mock_fwtool(self, meta_dict):
        extractor = OpenWrtMetadataExtractor(self._PATH)
        with mock.patch.object(
            extractor, "_extract_fwtool_metadata", return_value=meta_dict
        ):
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
        with mock.patch.object(
            extractor, "_extract_fwtool_metadata", return_value=None
        ):
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
    def setUp(self):
        self.extractor = OpenWrtMetadataExtractor(
            "/path/to/ath79-generic-tplink_tl-wdr4300-v1-squashfs-sysupgrade.bin"
        )

    def test_size_within_limit(self):
        with mock.patch(
            "openwisp_firmware_upgrader.settings.MAX_DECOMPRESSED_BYTES", 200
        ):
            self.extractor._check_limits(100, 100)  # must not raise

    def test_hard_limit_exceeded_raises(self):
        with mock.patch(
            "openwisp_firmware_upgrader.settings.MAX_DECOMPRESSED_BYTES", 200
        ):
            with self.assertRaises(DecompressionLimitExceeded):
                self.extractor._check_limits(300, 100)

    def test_ratio_exceeded_raises(self):
        with mock.patch(
            "openwisp_firmware_upgrader.settings.MAX_DECOMPRESSED_RATIO", 10
        ):
            with self.assertRaises(DecompressionLimitExceeded):
                self.extractor._check_limits(1100, 100)


class TestStripUimageHeader(TestCase):
    def setUp(self):
        self.extractor = OpenWrtMetadataExtractor(
            "/path/to/ath79-generic-tplink_tl-wdr4300-v1-squashfs-sysupgrade.bin"
        )

    def test_strips_64_byte_header_when_magic_matches(self):
        payload = b"kernel_data_here" * 10
        header = bytearray(UIMAGE_HEADER_SIZE)
        header[:4] = UIMAGE_MAGIC
        struct.pack_into(">I", header, 12, len(payload))
        data = bytes(header) + payload
        result = self.extractor._strip_uimage_header(data)
        self.assertEqual(result, payload)

    def test_passthrough_when_magic_does_not_match(self):
        data = b"\x00\x01\x02\x03" + b"x" * 100
        result = self.extractor._strip_uimage_header(data)
        self.assertEqual(result, data)

    def test_passthrough_when_data_shorter_than_header(self):
        data = UIMAGE_MAGIC + b"\x00" * 10
        result = self.extractor._strip_uimage_header(data)
        self.assertEqual(result, data)


class TestLocateDtb(TestCase):
    def setUp(self):
        self.extractor = OpenWrtMetadataExtractor(
            "/path/to/ath79-generic-tplink_tl-wdr4300-v1-squashfs-sysupgrade.bin"
        )

    def test_returns_none_when_no_dtb_magic(self):
        kernel = b"\xde\xad\xbe\xef" * 50
        self.assertIsNone(self.extractor._locate_dtb(kernel))

    def test_returns_none_when_candidate_size_below_minimum(self):
        bad_dtb = DTB_MAGIC + struct.pack(">I", DTB_MIN_SIZE - 1) + b"\x00" * 60
        self.assertIsNone(self.extractor._locate_dtb(b"\x00" * 100 + bad_dtb))


class TestIndividualDecompressors(TestCase):
    def setUp(self):
        self.extractor = OpenWrtMetadataExtractor(
            "/path/to/ath79-generic-tplink_tl-wdr4300-v1-squashfs-sysupgrade.bin"
        )

    def test_try_gzip_decompresses(self):
        original = b"Hello OpenWrt gzip"
        result = self.extractor._try_gzip(gzip.compress(original))
        self.assertEqual(result, original)

    def test_try_gzip_returns_none_for_wrong_magic(self):
        self.assertIsNone(self.extractor._try_gzip(b"\x00" * 20))

    def test_try_xz_decompresses(self):
        original = b"Hello OpenWrt xz"
        compressed = lzma.compress(original, format=lzma.FORMAT_XZ)
        result = self.extractor._try_xz(compressed)
        self.assertEqual(result, original)

    def test_try_xz_returns_none_for_wrong_magic(self):
        self.assertIsNone(self.extractor._try_xz(b"\x00" * 20))

    def test_try_lzma_decompresses(self):
        original = b"Hello OpenWrt lzma"
        compressed = lzma.compress(original, format=lzma.FORMAT_ALONE)
        result = self.extractor._try_lzma(compressed)
        self.assertEqual(result, original)

    def test_try_lzma_returns_none_for_wrong_magic(self):
        self.assertIsNone(self.extractor._try_lzma(b"\x00" * 20))

    def test_try_bz2_decompresses(self):
        original = b"Hello OpenWrt bz2"
        result = self.extractor._try_bz2(bz2.compress(original))
        self.assertEqual(result, original)

    def test_try_bz2_returns_none_for_wrong_magic(self):
        self.assertIsNone(self.extractor._try_bz2(b"\x00" * 20))

    def test_try_lz4_decompresses(self):
        original = b"Hello OpenWrt lz4"
        compressed = lz4frame.compress(original)
        result = self.extractor._try_lz4(compressed)
        self.assertEqual(result, original)

    def test_try_lz4_returns_none_for_wrong_magic(self):
        self.assertIsNone(self.extractor._try_lz4(b"\x00" * 20))


class TestDecompress(TestCase):
    def setUp(self):
        self.extractor = OpenWrtMetadataExtractor(
            "/path/to/ath79-generic-tplink_tl-wdr4300-v1-squashfs-sysupgrade.bin"
        )

    def test_gzip_decompressed(self):
        original = b"Hello OpenWrt firmware!"
        result = self.extractor._decompress(gzip.compress(original))
        self.assertEqual(result, original)

    def test_xz_decompressed(self):
        original = b"Hello OpenWrt firmware!"
        result = self.extractor._decompress(
            lzma.compress(original, format=lzma.FORMAT_XZ)
        )
        self.assertEqual(result, original)

    def test_bz2_decompressed(self):
        original = b"Hello OpenWrt firmware!"
        result = self.extractor._decompress(bz2.compress(original))
        self.assertEqual(result, original)

    def test_lzma_decompressed(self):
        original = b"Hello OpenWrt firmware!"
        result = self.extractor._decompress(
            lzma.compress(original, format=lzma.FORMAT_ALONE)
        )
        self.assertEqual(result, original)

    def test_unrecognised_format_returned_as_is(self):
        data = b"\x00\x01\x02\x03" * 10
        result = self.extractor._decompress(data)
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
        extractor = self._make_extractor("/path/to/openwrt-x86-64-generic.img")
        with mock.patch.object(
            extractor,
            "extract_from_image",
            side_effect=UnsupportedImageError("x86 not supported"),
        ):
            with mock.patch.object(extractor, "extract_from_dtb") as mock_dtb:
                with self.assertRaises(UnsupportedImageError):
                    extractor.extract()
        mock_dtb.assert_not_called()

    def test_tar_fallback_used_when_raw_bytes_have_no_dtb(self):
        extractor = self._make_extractor()
        tar_kernel = b"fake_kernel_data"
        with mock.patch.object(
            extractor, "_read_kernel_bytes", return_value=b"\x00" * 64
        ):
            with mock.patch.object(
                extractor, "_read_kernel_from_tar", return_value=tar_kernel
            ):
                with mock.patch.object(
                    extractor, "_locate_dtb", side_effect=[None, b"fake_dtb"]
                ):
                    with mock.patch.object(
                        extractor, "_metadata_from_dtb", return_value={"source": "dtb"}
                    ):
                        result = extractor.extract_from_dtb()
        self.assertEqual(result["source"], "dtb")


class TestExtractFwtoolMetadata(TestCase):
    def setUp(self):
        self.extractor = OpenWrtMetadataExtractor(
            "/path/to/ath79-generic-tplink_tl-wdr4300-v1-squashfs-sysupgrade.bin"
        )

    def _build_image(self, meta_dict, prefix=b"\x00" * 32):
        json_bytes = json.dumps(meta_dict).encode("utf-8")
        header = b"\x00" * HEADER_SIZE
        data_block = prefix + header + json_bytes
        size = HEADER_SIZE + len(json_bytes) + TRAILER_SIZE
        crc = self.extractor._crc32_block(0xFFFFFFFF, data_block)
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
            result = OpenWrtMetadataExtractor(path)._extract_fwtool_metadata()
        finally:
            os.unlink(path)
        self.assertIsNotNone(result)
        self.assertEqual(result["version"]["board"], "tplink,tl-wdr4300-v1")
        self.assertEqual(result["compat_version"], "1.0")

    def test_returns_none_when_no_trailer(self):
        path = self._write_image(b"\x00" * 256)
        try:
            result = OpenWrtMetadataExtractor(path)._extract_fwtool_metadata()
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
            result = OpenWrtMetadataExtractor(path)._extract_fwtool_metadata()
        finally:
            os.unlink(path)
        self.assertIsNone(result)


class TestRealFirmwareExtraction(TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sysupgrade = _get_firmware("sysupgrade")
        cls.sunxi = _get_firmware("sunxi")

    def test_sysupgrade_fwtool(self):
        if not self.sysupgrade:
            self.skipTest("sysupgrade image not available")
        result = OpenWrtMetadataExtractor(str(self.sysupgrade)).extract()
        self.assertEqual(result["source"], "fwtool")
        self.assertEqual(result["target"], "ath79/generic")
        self.assertIn("tplink,tl-wdr4300-v1", result["compatible"])
        self.assertEqual(result["version"], "23.05.5")

    def test_sunxi_dtb_fallback(self):
        if not self.sunxi:
            self.skipTest("sunxi image not available")
        result = OpenWrtMetadataExtractor(str(self.sunxi)).extract()
        self.assertTrue(result["model"])
        self.assertTrue(result["compatible"])
