class ExtractionError(Exception):
    pass


class UnsupportedImageError(ExtractionError):
    pass


class DecompressionLimitExceeded(ExtractionError):
    pass
