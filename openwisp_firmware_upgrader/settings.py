from django.conf import settings

from openwisp_controller.connection import settings as conn_settings

CUSTOM_OPENWRT_IMAGES = getattr(settings, 'OPENWISP_CUSTOM_OPENWRT_IMAGES', None)
# fmt: off
UPGRADERS_MAP = getattr(settings, 'OPENWISP_FIRMWARE_UPGRADERS_MAP', {
    conn_settings.DEFAULT_UPDATE_STRATEGIES[0][0]: 'openwisp_firmware_upgrader.upgraders.openwrt.OpenWrt'
})
# fmt: on

MAX_FILE_SIZE = getattr(
    settings, 'OPENWISP_FIRMWARE_UPGRADER_MAX_FILE_SIZE', 30 * 1024 * 1024
)

RETRY_OPTIONS = getattr(
    settings,
    'OPENWISP_FIRMWARE_UPGRADER_RETRY_OPTIONS',
    dict(max_retries=4, retry_backoff=60, retry_backoff_max=600, retry_jitter=True),
)

TASK_TIMEOUT = getattr(settings, 'OPENWISP_FIRMWARE_UPGRADER_TASK_TIMEOUT', 600)

FIRMWARE_UPGRADER_API = getattr(settings, 'OPENWISP_FIRMWARE_UPGRADER_API', False)
OPENWRT_SETTINGS = getattr(settings, 'OPENWISP_FIRMWARE_UPGRADER_OPENWRT_SETTINGS', {})
