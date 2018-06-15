from django.conf import settings

CUSTOM_OPENWRT_IMAGES = getattr(settings, 'OPENWISP_CUSTOM_OPENWRT_IMAGES', None)
