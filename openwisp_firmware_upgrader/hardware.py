"""
Mapping between hardware models and firwmare image
This if focused on OpenWRT only fpr now, but it should
be possible to add support for different embedded
systems in the future.
"""
from collections import OrderedDict

from . import settings as app_settings

if app_settings.CUSTOM_OPENWRT_IMAGES:
    OPENWRT_FIRMWARE_IMAGE_MAP = OrderedDict(app_settings.CUSTOM_OPENWRT_IMAGES)
else:  # pragma: no cover
    OPENWRT_FIRMWARE_IMAGE_MAP = OrderedDict()

OPENWRT_FIRMWARE_IMAGE_MAP.update(
    OrderedDict(
        (
            (
                'ramips-mt76x8-gl-mt300n-v2-squashfs-sysupgrade.bin',
                {'label': 'GL.iNet GL-MT300N-V2', 'boards': ('GL-MT300N-V2',)},
            ),
            (
                'ar71xx-generic-tl-wdr4300-v1-il-squashfs-sysupgrade.bin',
                {
                    'label': 'TP-Link WDR4300 v1 (IL)',
                    'boards': ('TP-LINK TL-WDR4300 v1 (IL)',),
                },
            ),
            (
                'ar71xx-generic-tl-wdr4300-v1-squashfs-sysupgrade.bin',
                {'label': 'TP-Link WDR4300 v1', 'boards': ('TP-Link TL-WDR4300 v1',)},
            ),
            (
                'ar71xx-generic-xd3200-squashfs-sysupgrade.bin',
                {'label': 'YunCore XD3200', 'boards': ('YunCore XD3200',)},
            ),
            (
                'ar71xx-generic-ubnt-airrouter-squashfs-sysupgrade.bin',
                {'label': 'Ubiquiti AirRouter', 'boards': ('Ubiquiti AirRouter',)},
            ),
        )
    )
)

# OpenWRT only for now, in the future we'll merge
# different dictionaries representing different firmwares
# eg: AirOS, Raspbian
FIRMWARE_IMAGE_MAP = OPENWRT_FIRMWARE_IMAGE_MAP

# Allows getting type from image board
REVERSE_FIRMWARE_IMAGE_MAP = {}
# Choices used in model
FIRMWARE_IMAGE_TYPE_CHOICES = []

for key, info in FIRMWARE_IMAGE_MAP.items():
    FIRMWARE_IMAGE_TYPE_CHOICES.append((key, info['label']))
    for board in info['boards']:
        REVERSE_FIRMWARE_IMAGE_MAP[board] = key
