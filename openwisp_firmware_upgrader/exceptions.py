class FirmwareUpgraderException(Exception):
    pass


class UpgradeNotNeeded(FirmwareUpgraderException):
    """
    Raised when the upgrade is not needed
    """


class UpgradeAborted(FirmwareUpgraderException):
    """
    Raised when the upgrade has to be flagged as aborted
    """


class ReconnectionFailed(FirmwareUpgraderException):
    """
    Raised when the reconnection after the upgrade fails
    """


class RecoverableFailure(FirmwareUpgraderException):
    """
    Raised when the upgrade can be retried
    """
