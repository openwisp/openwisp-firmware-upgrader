from abc import ABC, abstractmethod
from django.utils.translation import gettext_lazy as _
from .exceptions import ExtractionError, UnsupportedImageError


class BaseMetadataExtractor(ABC):

    def extract(self, image_path):
        try:
            return self.extract_from_image(image_path)

        except ExtractionError:
            return self.extract_from_dtb(image_path)

    @abstractmethod
    def extract_from_image(self, image_path):
        pass

    def extract_from_dtb(self, image_path):
        raise UnsupportedImageError(
            _("DTB extraction is not supported for this image type.")
        )
