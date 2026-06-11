import bz2
import gzip
import hashlib
import io
import json
import lzma
import os
import struct
import tarfile
import tempfile
import urllib.request
import zlib
from pathlib import Path
from unittest import mock

import fdt
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
        with urllib.request.urlopen(entry["url"], timeout=60) as resp:
            with open(cached, "wb") as out:
                out.write(resp.read())
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

    def test_non_dict_meta_raises_extraction_error(self):
        extractor = OpenWrtMetadataExtractor(self._PATH)
        with mock.patch.object(extractor, "_extract_fwtool_metadata", return_value=[]):
            with self.assertRaises(ExtractionError):
                extractor.extract_from_image()

    def test_non_dict_version_raises_extraction_error(self):
        extractor = OpenWrtMetadataExtractor(self._PATH)
        with mock.patch.object(
            extractor, "_extract_fwtool_metadata", return_value={"version": []}
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


class TestTryExtractDtbFromKernel(TestCase):
    @staticmethod
    def _make_dtb(model="Test Router v1", compatible="test,router-v1"):
        tree = fdt.FDT()
        tree.header.version = 17
        tree.header.last_comp_version = 16
        tree.root.set_property("model", model)
        tree.root.set_property("compatible", compatible)
        return tree.to_dtb()

    def setUp(self):
        self.extractor = OpenWrtMetadataExtractor(
            "/path/to/ath79-generic-tplink_tl-wdr4300-v1-squashfs-sysupgrade.bin"
        )

    def _kernel_with_dtb(self, compress_fn, model="Test Router v1"):
        dtb = self._make_dtb(model=model)
        return compress_fn(b"\x00" * 128 + dtb + b"\x00" * 64)

    def test_gzip_kernel_extracts_dtb(self):
        kernel = self._kernel_with_dtb(gzip.compress, model="Gzip Router")
        result = self.extractor._try_extract_dtb_from_kernel(kernel)
        self.assertIsNotNone(result)
        self.assertEqual(
            self.extractor._metadata_from_dtb(result)["model"], "Gzip Router"
        )

    def test_xz_kernel_extracts_dtb(self):
        kernel = self._kernel_with_dtb(
            lambda d: lzma.compress(d, format=lzma.FORMAT_XZ), model="XZ Router"
        )
        result = self.extractor._try_extract_dtb_from_kernel(kernel)
        self.assertIsNotNone(result)
        self.assertEqual(
            self.extractor._metadata_from_dtb(result)["model"], "XZ Router"
        )

    def test_bz2_kernel_extracts_dtb(self):
        kernel = self._kernel_with_dtb(bz2.compress, model="BZ2 Router")
        result = self.extractor._try_extract_dtb_from_kernel(kernel)
        self.assertIsNotNone(result)
        self.assertEqual(
            self.extractor._metadata_from_dtb(result)["model"], "BZ2 Router"
        )

    def test_lzma_kernel_extracts_dtb(self):
        kernel = self._kernel_with_dtb(
            lambda d: lzma.compress(d, format=lzma.FORMAT_ALONE), model="LZMA Router"
        )
        result = self.extractor._try_extract_dtb_from_kernel(kernel)
        self.assertIsNotNone(result)
        self.assertEqual(
            self.extractor._metadata_from_dtb(result)["model"], "LZMA Router"
        )

    def test_lz4_kernel_extracts_dtb(self):
        kernel = self._kernel_with_dtb(lz4frame.compress, model="LZ4 Router")
        result = self.extractor._try_extract_dtb_from_kernel(kernel)
        self.assertIsNotNone(result)
        self.assertEqual(
            self.extractor._metadata_from_dtb(result)["model"], "LZ4 Router"
        )

    def test_double_decompressed_gzip_xz_kernel_extracts_dtb(self):
        dtb = self._make_dtb(model="Double Compressed Router")
        inner = lzma.compress(b"\x00" * 128 + dtb + b"\x00" * 64, format=lzma.FORMAT_XZ)
        kernel = gzip.compress(inner)
        result = self.extractor._try_extract_dtb_from_kernel(kernel)
        self.assertIsNotNone(result)
        self.assertEqual(
            self.extractor._metadata_from_dtb(result)["model"],
            "Double Compressed Router",
        )

    def test_uimage_header_stripped_before_decompress(self):
        dtb = self._make_dtb(model="UImage Device")
        payload = gzip.compress(b"\x00" * 64 + dtb + b"\x00" * 32)
        header = bytearray(UIMAGE_HEADER_SIZE)
        header[:4] = UIMAGE_MAGIC
        struct.pack_into(">I", header, 12, len(payload))
        kernel = bytes(header) + payload
        result = self.extractor._try_extract_dtb_from_kernel(kernel)
        self.assertIsNotNone(result)
        self.assertEqual(
            self.extractor._metadata_from_dtb(result)["model"], "UImage Device"
        )

    def test_no_dtb_in_payload_returns_none(self):
        kernel = gzip.compress(b"\xff" * 256)
        self.assertIsNone(self.extractor._try_extract_dtb_from_kernel(kernel))

    def test_unrecognized_data_returns_none(self):
        self.assertIsNone(
            self.extractor._try_extract_dtb_from_kernel(b"\xde\xad\xbe\xef" * 50)
        )

    def test_decompression_hard_limit_exceeded_propagates(self):
        kernel = gzip.compress(b"\x00" * 600)
        with mock.patch(
            "openwisp_firmware_upgrader.settings.MAX_DECOMPRESSED_BYTES", 512
        ):
            with self.assertRaises(DecompressionLimitExceeded) as cm:
                self.extractor._try_extract_dtb_from_kernel(kernel)
        self.assertIn("MB", str(cm.exception))

    def test_decompression_ratio_limit_exceeded_propagates(self):
        kernel = gzip.compress(b"\x00" * 1100)
        with mock.patch(
            "openwisp_firmware_upgrader.settings.MAX_DECOMPRESSED_RATIO", 10
        ):
            with self.assertRaises(DecompressionLimitExceeded) as cm:
                self.extractor._try_extract_dtb_from_kernel(kernel)
        self.assertIn("ratio", str(cm.exception).lower())

    def test_nested_compressed_dtb_found_via_deep_scan(self):
        dtb = self._make_dtb(model="Nested Device")
        inner = gzip.compress(b"\xff" * 128 + dtb + b"\xff" * 64)
        outer = b"\x00" * 200 + inner + b"\x00" * 50
        result = self.extractor._try_extract_dtb_from_kernel(outer)
        self.assertIsNotNone(result)
        self.assertEqual(
            self.extractor._metadata_from_dtb(result)["model"], "Nested Device"
        )

    def test_fit_image_with_embedded_dtb_extracts_model(self):
        inner_dtb = self._make_dtb(model="FIT Device")
        fit = fdt.FDT()
        fit.header.version = 17
        fit.header.last_comp_version = 16
        fit.root.append(fdt.Node("images"))
        fit_bytes = bytearray(fit.to_dtb())
        struct.pack_into(">I", fit_bytes, 4, len(fit_bytes) + len(inner_dtb))
        kernel = bytes(fit_bytes) + inner_dtb
        result = self.extractor._try_extract_dtb_from_kernel(kernel)
        self.assertIsNotNone(result)
        self.assertEqual(
            self.extractor._metadata_from_dtb(result)["model"], "FIT Device"
        )


class TestExtractOverride(TestCase):
    _PATH = "/path/to/ath79-generic-tplink_tl-wdr4300-v1-squashfs-sysupgrade.bin"

    def _make_extractor(self, path=None):
        return OpenWrtMetadataExtractor(path or self._PATH)

    @mock.patch.object(
        OpenWrtMetadataExtractor,
        "extract_from_dtb",
        side_effect=UnsupportedImageError("no dtb"),
    )
    @mock.patch.object(OpenWrtMetadataExtractor, "extract_from_image")
    def test_fwtool_success_returns_fwtool_result(self, mock_image, _mock_dtb):
        extractor = self._make_extractor()
        mock_image.return_value = {
            "model": "x",
            "compatible": ["x"],
            "target": "x",
            "version": "x",
            "compat_version": "1.0",
            "source": "fwtool",
        }
        result = extractor.extract()
        self.assertEqual(result["source"], "fwtool")

    @mock.patch.object(OpenWrtMetadataExtractor, "extract_from_dtb")
    @mock.patch.object(
        OpenWrtMetadataExtractor,
        "extract_from_image",
        side_effect=ExtractionError("fail"),
    )
    def test_fwtool_failure_falls_back_to_dtb(self, _mock_image, mock_dtb):
        extractor = self._make_extractor()
        mock_dtb.return_value = {
            "model": "dtb-model",
            "compatible": ["dtb,compat"],
            "target": "",
            "version": "",
            "compat_version": "1.0",
            "source": "dtb",
        }
        result = extractor.extract()
        self.assertEqual(result["source"], "dtb")

    @mock.patch.object(
        OpenWrtMetadataExtractor,
        "extract_from_dtb",
        side_effect=UnsupportedImageError("no dtb"),
    )
    @mock.patch.object(
        OpenWrtMetadataExtractor,
        "extract_from_image",
        side_effect=ExtractionError("fail"),
    )
    def test_both_paths_fail_raises(self, _mock_image, _mock_dtb):
        extractor = self._make_extractor()
        with self.assertRaises(UnsupportedImageError):
            extractor.extract()

    @mock.patch.object(OpenWrtMetadataExtractor, "extract_from_image")
    @mock.patch.object(OpenWrtMetadataExtractor, "extract_from_dtb")
    def test_dtb_enriches_missing_compatible(self, mock_dtb, mock_image):
        extractor = self._make_extractor()
        mock_image.return_value = {
            "model": "x",
            "compatible": [],
            "target": "x",
            "version": "x",
            "compat_version": "1.0",
            "source": "fwtool",
        }
        mock_dtb.return_value = {
            "model": "",
            "compatible": ["enriched,compat"],
            "target": "",
            "version": "",
            "compat_version": "1.0",
            "source": "dtb",
        }
        result = extractor.extract()
        self.assertIn("enriched,compat", result["compatible"])
        self.assertEqual(result["source"], "fwtool")

    @mock.patch.object(OpenWrtMetadataExtractor, "extract_from_image")
    @mock.patch.object(OpenWrtMetadataExtractor, "extract_from_dtb")
    def test_dtb_model_overrides_fwtool_board_id(self, mock_dtb, mock_image):
        extractor = self._make_extractor()
        mock_image.return_value = {
            "model": "tplink_archer-c6-v3",
            "compatible": ["tplink,archer-c6-v3"],
            "target": "ramips/mt7621",
            "version": "24.10.6",
            "compat_version": "1.0",
            "source": "fwtool",
        }
        mock_dtb.return_value = {
            "model": "TP-Link Archer C6 v3",
            "compatible": ["tplink,archer-c6-v3"],
            "target": "",
            "version": "",
            "compat_version": "1.0",
            "source": "dtb",
        }
        result = extractor.extract()
        self.assertEqual(result["model"], "TP-Link Archer C6 v3")
        self.assertEqual(result["source"], "fwtool")

    @mock.patch.object(
        OpenWrtMetadataExtractor,
        "extract_from_image",
        side_effect=UnsupportedImageError("x86 not supported"),
    )
    @mock.patch.object(OpenWrtMetadataExtractor, "extract_from_dtb")
    def test_unsupported_image_error_propagates_without_dtb_attempt(
        self, mock_dtb, _mock_image
    ):
        extractor = self._make_extractor("/path/to/openwrt-x86-64-generic.img")
        with self.assertRaises(UnsupportedImageError):
            extractor.extract()
        mock_dtb.assert_not_called()

    @mock.patch.object(
        OpenWrtMetadataExtractor, "_metadata_from_dtb", return_value={"source": "dtb"}
    )
    @mock.patch.object(
        OpenWrtMetadataExtractor, "_locate_dtb", side_effect=[None, b"fake_dtb"]
    )
    @mock.patch.object(
        OpenWrtMetadataExtractor,
        "_read_kernel_from_tar",
        return_value=b"fake_kernel_data",
    )
    @mock.patch.object(
        OpenWrtMetadataExtractor, "_read_kernel_bytes", return_value=b"\x00" * 64
    )
    def test_tar_fallback_used_when_raw_bytes_have_no_dtb(
        self, _mock_read, _mock_tar, _mock_locate, _mock_metadata
    ):
        extractor = self._make_extractor()
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
        crc = zlib.crc32(data_block) ^ 0xFFFFFFFF
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


class TestReadKernelFromTar(TestCase):
    def _write_tar(self, members):
        f = tempfile.NamedTemporaryFile(suffix=".tar", delete=False)
        f.close()
        with tarfile.open(f.name, mode="w") as tf:
            for name, content in members:
                info = tarfile.TarInfo(name)
                info.size = len(content)
                tf.addfile(info, io.BytesIO(content))
        return f.name

    def test_returns_kernel_bytes_for_matching_member(self):
        payload = DTB_MAGIC + b"\x00" * 60
        path = self._write_tar([("sysupgrade-kernel", payload)])
        try:
            result = OpenWrtMetadataExtractor(path)._read_kernel_from_tar()
        finally:
            os.unlink(path)
        self.assertEqual(result, payload)

    def test_oversized_tar_member_raises(self):
        path = self._write_tar([("kernel.bin", b"\x00" * 128)])
        try:
            extractor = OpenWrtMetadataExtractor(path)
            with mock.patch("openwisp_firmware_upgrader.settings.MAX_KERNEL_BYTES", 64):
                with self.assertRaises(DecompressionLimitExceeded):
                    extractor._read_kernel_from_tar()
        finally:
            os.unlink(path)


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
