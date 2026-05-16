from django.test import TestCase
from ..extractors.base import BaseMetadataExtractor
from ..extractors.exceptions import ExtractionError, UnsupportedImageError
from ..upgraders.openwrt import OpenWrt


class ConcreteSuccessExtractor(BaseMetadataExtractor):
    def extract_from_image(self, image_path):
        return {
            "model": "Test Router",
            "compatible": ["test,router-v1"],
            "target": "ath79/generic",
            "version": "23.05.0",
            "compat_version": "1.0",
            "source": "fwtool",
        }


class ConcreteFailExtractor(BaseMetadataExtractor):
    def extract_from_image(self, image_path):
        raise ExtractionError("no trailer found")


class ConcreteDTBExtractor(ConcreteFailExtractor):
    def extract_from_dtb(self, image_path):
        return {
            "model": "Sunxi Board",
            "compatible": ["allwinner,sun8i-h3"],
            "target": "sunxi/cortexa7",
            "version": "23.05.0",
            "compat_version": "1.0",
            "source": "dtb",
        }


class TestBaseMetadataExtractor(TestCase):
    def test_extract_fast_path_success(self):
        result = ConcreteSuccessExtractor().extract("/fake/path.bin")
        self.assertEqual(result["source"], "fwtool")

    def test_extract_falls_back_to_dtb(self):
        result = ConcreteDTBExtractor().extract("/fake/path.bin")
        self.assertEqual(result["source"], "dtb")

    def test_extract_reraises_when_both_paths_fail(self):
        with self.assertRaises(UnsupportedImageError):
            ConcreteFailExtractor().extract("/fake/path.bin")

    def test_extract_from_dtb_raises_by_default(self):
        with self.assertRaises(UnsupportedImageError):
            ConcreteSuccessExtractor().extract_from_dtb("/fake/path.bin")

    def test_metadata_extractor_class_is_none_on_openwrt(self):
        self.assertTrue(hasattr(OpenWrt, "metadata_extractor_class"))
        self.assertIsNone(OpenWrt.metadata_extractor_class)
