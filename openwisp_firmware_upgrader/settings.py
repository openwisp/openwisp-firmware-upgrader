from django.conf import settings

from openwisp_controller.connection import settings as conn_settings

CUSTOM_OPENWRT_IMAGES = getattr(settings, 'OPENWISP_CUSTOM_OPENWRT_IMAGES', None)
UPGRADERS_MAP = getattr(settings, 'OPENWISP_FIRMWARE_UPGRADERS_MAP', {
    conn_settings.DEFAULT_UPDATE_STRATEGIES[0][0]: 'openwisp_firmware_upgrader.upgraders.openwrt.OpenWrt'
})
