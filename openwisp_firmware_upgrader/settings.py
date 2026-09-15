from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from openwisp_controller.connection import settings as conn_settings

CUSTOM_OPENWRT_IMAGES = getattr(settings, "OPENWISP_CUSTOM_OPENWRT_IMAGES", None)
# fmt: off
UPGRADERS_MAP = getattr(settings, 'OPENWISP_FIRMWARE_UPGRADERS_MAP', {
    conn_settings.DEFAULT_UPDATE_STRATEGIES[0][0]: 'openwisp_firmware_upgrader.upgraders.openwrt.OpenWrt',
    conn_settings.DEFAULT_UPDATE_STRATEGIES[1][0]: 'openwisp_firmware_upgrader.upgraders.openwisp.OpenWisp1'
})
# fmt: on

MAX_FILE_SIZE = getattr(
    settings, "OPENWISP_FIRMWARE_UPGRADER_MAX_FILE_SIZE", 30 * 1024 * 1024
)

RETRY_OPTIONS = getattr(
    settings,
    "OPENWISP_FIRMWARE_UPGRADER_RETRY_OPTIONS",
    dict(max_retries=4, retry_backoff=60, retry_backoff_max=600, retry_jitter=True),
)

TASK_TIMEOUT = getattr(settings, "OPENWISP_FIRMWARE_UPGRADER_TASK_TIMEOUT", 1500)

PERSISTENT_RETRY_OPTIONS = dict(
    base_delay=600,
    multiplier=2,
    jitter=0.25,
    max_delay=43200,
    dispatch_jitter=300,
    signal_jitter=120,
    claim_timeout=3600,
)
PERSISTENT_RETRY_OPTIONS.update(
    getattr(settings, "OPENWISP_FIRMWARE_UPGRADER_PERSISTENT_RETRY_OPTIONS", {})
)
if (
    PERSISTENT_RETRY_OPTIONS["base_delay"] <= 0
    or PERSISTENT_RETRY_OPTIONS["max_delay"] <= 0
    or PERSISTENT_RETRY_OPTIONS["multiplier"] < 1
    or not 0 <= PERSISTENT_RETRY_OPTIONS["jitter"] < 1
    or PERSISTENT_RETRY_OPTIONS["dispatch_jitter"] <= 0
    or PERSISTENT_RETRY_OPTIONS["signal_jitter"] < 0
):
    raise ImproperlyConfigured(
        "OPENWISP_FIRMWARE_UPGRADER_PERSISTENT_RETRY_OPTIONS requires "
        "base_delay > 0, max_delay > 0, multiplier >= 1, 0 <= jitter < 1, "
        "dispatch_jitter > 0 and signal_jitter >= 0"
    )
if PERSISTENT_RETRY_OPTIONS["claim_timeout"] <= TASK_TIMEOUT + RETRY_OPTIONS.get(
    "retry_backoff_max", 600
):
    raise ImproperlyConfigured(
        "OPENWISP_FIRMWARE_UPGRADER_PERSISTENT_RETRY_OPTIONS['claim_timeout'] "
        "must be greater than OPENWISP_FIRMWARE_UPGRADER_TASK_TIMEOUT plus the "
        "retry_backoff_max of OPENWISP_FIRMWARE_UPGRADER_RETRY_OPTIONS"
    )
PERSISTENT_REMINDER_PERIOD = getattr(
    settings, "OPENWISP_FIRMWARE_UPGRADER_PERSISTENT_REMINDER_PERIOD", 5184000
)
if PERSISTENT_REMINDER_PERIOD <= 0:
    raise ImproperlyConfigured(
        "OPENWISP_FIRMWARE_UPGRADER_PERSISTENT_REMINDER_PERIOD must be positive"
    )

SCHEDULE_MIN_DELAY = getattr(
    settings, "OPENWISP_FIRMWARE_UPGRADER_SCHEDULE_MIN_DELAY", 600
)
SCHEDULE_MAX_HORIZON = getattr(
    settings, "OPENWISP_FIRMWARE_UPGRADER_SCHEDULE_MAX_HORIZON", 15552000
)
if SCHEDULE_MIN_DELAY < 0:
    raise ImproperlyConfigured(
        "OPENWISP_FIRMWARE_UPGRADER_SCHEDULE_MIN_DELAY cannot be negative"
    )
if SCHEDULE_MAX_HORIZON <= 0:
    raise ImproperlyConfigured(
        "OPENWISP_FIRMWARE_UPGRADER_SCHEDULE_MAX_HORIZON must be positive"
    )
if SCHEDULE_MIN_DELAY >= SCHEDULE_MAX_HORIZON:
    raise ImproperlyConfigured(
        "OPENWISP_FIRMWARE_UPGRADER_SCHEDULE_MIN_DELAY must be smaller than "
        "OPENWISP_FIRMWARE_UPGRADER_SCHEDULE_MAX_HORIZON"
    )
SCHEDULE_LAUNCH_TIMEOUT = getattr(
    settings, "OPENWISP_FIRMWARE_UPGRADER_SCHEDULE_LAUNCH_TIMEOUT", 300
)
if SCHEDULE_LAUNCH_TIMEOUT <= 0:
    raise ImproperlyConfigured(
        "OPENWISP_FIRMWARE_UPGRADER_SCHEDULE_LAUNCH_TIMEOUT must be positive"
    )

FIRMWARE_UPGRADER_API = getattr(settings, "OPENWISP_FIRMWARE_UPGRADER_API", True)
FIRMWARE_API_BASEURL = getattr(settings, "OPENWISP_FIRMWARE_API_BASEURL", "/")
OPENWRT_SETTINGS = getattr(settings, "OPENWISP_FIRMWARE_UPGRADER_OPENWRT_SETTINGS", {})

# Path of urls that need to be refered in migrations files.
IMAGE_URL_PATH = "firmware/"

try:
    PRIVATE_STORAGE_INSTANCE = import_string(
        getattr(
            settings,
            "OPENWISP_FIRMWARE_PRIVATE_STORAGE_INSTANCE",
            "openwisp_firmware_upgrader.private_storage.storage.file_system_private_storage",
        )
    )
except ImportError:
    raise ImproperlyConfigured(
        "Failed to import FIRMWARE_UPGRADER_PRIVATE_STORAGE_INSTANCE"
    )
