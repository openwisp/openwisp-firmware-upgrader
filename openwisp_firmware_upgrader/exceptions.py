class UpgradeNotNeeded(Exception):
    """
    Raised when the upgrade is not needed
    """


class AbortedUpgrade(Exception):
    """
    Raised when the upgrade has to be flagged as aborted
    """


class FailedUpgrade(Exception):
    """
    Raised when the upgrade has to be flagged as failed
    """


class RecoverableFailure(Exception):
    """
    Raised when the upgrade has to be retried
    """
