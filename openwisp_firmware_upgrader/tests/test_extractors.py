from django.test import TestCase

from ..extractors.base import BaseMetadataExtractor
from ..extractors.exceptions import ExtractionError, UnsupportedImageError


class ConcreteSuccessExtractor(BaseMetadataExtractor):
    def extract_from_image(self):
        return {
            "model": "Test Device",
            "compatible": ["test,device"],
            "target": "ath79/generic",
            "version": "0.1",
            "compat_version": "1.0",
            "source": "fwtool",
        }


class ConcreteFailExtractor(BaseMetadataExtractor):
    def extract_from_image(self):
        raise ExtractionError("no trailer found")


class ConcreteUnsupportedExtractor(BaseMetadataExtractor):
    def extract_from_image(self):
        raise UnsupportedImageError("not supported")


class ConcreteDTBExtractor(ConcreteFailExtractor):
    def extract_from_dtb(self):
        return {
            "model": "Test Device",
            "compatible": ["test,device"],
            "target": "",
            "version": "",
            "compat_version": "1.0",
            "source": "dtb",
        }


class TestBaseMetadataExtractor(TestCase):
    def test_extract_fast_path_success(self):
        extractor = ConcreteSuccessExtractor("/fake/path.bin")
        result = extractor.extract()
        self.assertEqual(result["source"], "fwtool")
        self.assertEqual(result["model"], "Test Device")

    def test_extract_falls_back_to_dtb_on_extraction_error(self):
        extractor = ConcreteDTBExtractor("/fake/path.bin")
        result = extractor.extract()
        self.assertEqual(result["source"], "dtb")

    def test_extract_reraises_when_both_paths_fail(self):
        extractor = ConcreteFailExtractor("/fake/path.bin")
        with self.assertRaises(UnsupportedImageError):
            extractor.extract()

    def test_unsupported_image_error_not_caught_by_extract(self):
        extractor = ConcreteUnsupportedExtractor("/fake/path.bin")
        with self.assertRaises(UnsupportedImageError):
            extractor.extract()

    def test_extract_from_dtb_raises_by_default(self):
        extractor = ConcreteSuccessExtractor("/fake/path.bin")
        with self.assertRaises(UnsupportedImageError):
            extractor.extract_from_dtb()

    def test_image_path_stored_as_string(self):
        from pathlib import Path

        extractor = ConcreteSuccessExtractor(Path("/fake/path.bin"))
        self.assertIsInstance(extractor.image_path, str)
        self.assertEqual(extractor.image_path, "/fake/path.bin")
