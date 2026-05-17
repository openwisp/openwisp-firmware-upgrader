from abc import ABC, abstractmethod

from django.utils.translation import gettext_lazy as _

from .exceptions import ExtractionError, UnsupportedImageError


class BaseMetadataExtractor(ABC):

    def __init__(self, image_path):
        self.image_path = str(image_path)

    def extract(self):
        try:
            return self.extract_from_image()
        except UnsupportedImageError:
            raise
        except ExtractionError:
            return self.extract_from_dtb()

    @abstractmethod
    def extract_from_image(self):
        pass

    def extract_from_dtb(self):
        raise UnsupportedImageError(
            _("DTB extraction is not supported for this image type.")
        )
