import fnmatch

from compress_staticfiles.storage import (
    CompressStaticFilesStorage as BaseCompressStaticFilesStorage,
)
from django.conf import settings


class FileHashedNameMixin:
    default_excluded_patterns = ['leaflet/*/*.png']
    excluded_patterns = default_excluded_patterns + getattr(
        settings, "OPENWISP_STATICFILES_VERSIONED_EXCLUDE", []
    )

    def hashed_name(self, name, content=None, filename=None):
        if not any(
            fnmatch.fnmatch(name, pattern) for pattern in self.excluded_patterns
        ):
            return super().hashed_name(name, content, filename)
        return name


class CompressStaticFilesStorage(
    FileHashedNameMixin,
    BaseCompressStaticFilesStorage,
):
    """Like CompressStaticFilesStorage, but allows excluding some files."""

    pass
