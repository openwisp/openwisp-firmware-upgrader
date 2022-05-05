"""
Mapping between hardware models and firwmare image
This if focused on OpenWRT only for now, but it should
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
                'ar71xx-generic-cf-e320n-v2-squashfs-sysupgrade.bin',
                {
                    'label': 'COMFAST CF-E320N v2 (OpenWRT 19.07 and earlier)',
                    'boards': ('COMFAST CF-E320N v2',),
                },
            ),
            (
                'ipq40xx-generic-engenius_eap1300-squashfs-sysupgrade.bin',
                {
                    'label': 'EnGenius EAP1300',
                    'boards': ('EnGenius EAP1300',),
                },
            ),
            (
                'ramips-mt76x8-gl-mt300n-v2-squashfs-sysupgrade.bin',
                {'label': 'GL.iNet GL-MT300N-V2', 'boards': ('GL-MT300N-V2',)},
            ),
            (
                'mvebu-cortexa9-linksys_wrt1900acs-squashfs-sysupgrade.img',
                {'label': 'Linksys WRT1900ACS', 'boards': ('Linksys WRT1900ACS',)},
            ),
            (
                'mvebu-cortexa9-linksys_wrt3200acm-squashfs-sysupgrade.img',
                {'label': 'Linksys WRT3200ACM', 'boards': ('Linksys WRT3200ACM',)},
            ),
            (
                'brcm2708-bcm2709-rpi-2-ext4-sysupgrade.img.gz',
                {
                    'label': 'Raspberry Pi 2 Model B',
                    'boards': (
                        'Raspberry Pi 2 Model B Rev 1.0',
                        'Raspberry Pi 2 Model B Rev 1.1',
                        'Raspberry Pi 2 Model B Rev 1.2',
                    ),
                },
            ),
            (
                'brcm2708-bcm2710-rpi-3-ext4-sysupgrade.img.gz',
                {
                    'label': 'Raspberry Pi 3 Model B',
                    'boards': ('Raspberry Pi 3 Model B Rev 1.2',),
                },
            ),
            (
                'ar71xx-generic-archer-c7-v1-squashfs-sysupgrade.bin',
                {
                    'label': 'TP-Link Archer C7 v1 (OpenWRT 19.07 and earlier)',
                    'boards': ('tplink,archer-c7-v1',),
                },
            ),
            (
                'ath79-generic-tplink_archer-c7-v1-squashfs-sysupgrade.bin',
                {
                    'label': 'TP-Link Archer C7 v1 (OpenWRT 19.07 and later)',
                    'boards': ('tplink,archer-c7-v1',),
                },
            ),
            (
                'ar71xx-generic-archer-c7-v2-squashfs-sysupgrade.bin',
                {
                    'label': 'TP-Link Archer C7 v2 (OpenWRT 19.07 and earlier)',
                    'boards': ('TP-Link Archer C7 v2', 'TP-Link Archer C7 v3'),
                },
            ),
            (
                'ath79-generic-tplink_archer-c7-v2-squashfs-sysupgrade.bin',
                {
                    'label': 'TP-Link Archer C7 v2 (OpenWRT 19.07 and later)',
                    'boards': ('TP-Link Archer C7 v2', 'TP-Link Archer C7 v3'),
                },
            ),
            (
                'ar71xx-generic-archer-c7-v4-squashfs-sysupgrade.bin',
                {
                    'label': 'TP-Link Archer C7 v4 (OpenWRT 19.07 and earlier)',
                    'boards': ('TP-Link Archer C7 v4',),
                },
            ),
            (
                'ath79-generic-tplink_archer-c7-v4-squashfs-sysupgrade.bin',
                {
                    'label': 'TP-Link Archer C7 v4 (OpenWRT 19.07 and later)',
                    'boards': ('TP-Link Archer C7 v4',),
                },
            ),
            (
                'ar71xx-generic-archer-c7-v5-squashfs-sysupgrade.bin',
                {
                    'label': 'TP-Link Archer C7 v5 (OpenWRT 19.07 and earlier)',
                    'boards': ('TP-Link Archer C7 v5',),
                },
            ),
            (
                'ath79-generic-tplink_archer-c7-v5-squashfs-sysupgrade.bin',
                {
                    'label': 'TP-Link Archer C7 v5 (OpenWRT 19.07 and later)',
                    'boards': ('TP-Link Archer C7 v5',),
                },
            ),
            (
                'ramips-mt76x8-tplink_archer-c50-v4-squashfs-sysupgrade.bin',
                {
                    'label': 'TP-Link Archer C50 v4',
                    'boards': ('TP-Link Archer C50 v4',),
                },
            ),
            (
                'ar71xx-generic-cpe210-220-v1-squashfs-sysupgrade.bin',
                {
                    'label': 'TP-LINK CPE210 v3 (OpenWRT 19.07 and earlier)',
                    'boards': ('TP-LINK CPE210 v1', 'TP-LINK CPE220 v1'),
                },
            ),
            (
                'ath79-generic-tplink_cpe210-v2-squashfs-sysupgrade.bin',
                {
                    'label': 'TP-LINK CPE210 v2 (OpenWRT 19.07 and later)',
                    'boards': ('TP-LINK CPE210 v2',),
                },
            ),
            (
                'ath79-generic-tplink_cpe210-v3-squashfs-sysupgrade.bin',
                {
                    'label': 'TP-LINK CPE210 v3 (OpenWRT 19.07 and later)',
                    'boards': ('TP-LINK CPE210 v3',),
                },
            ),
            (
                'ath79-generic-tplink_cpe510-v3-squashfs-sysupgrade.bin',
                {
                    'label': 'TP-LINK CPE510 v3 (OpenWRT 19.07 and later)',
                    'boards': ('TP-LINK CPE510 v3',),
                },
            ),
            (
                'ar71xx-generic-tl-wdr3600-v1-squashfs-sysupgrade.bin',
                {
                    'label': 'TP-Link WDR3600 v1 (OpenWRT 19.07 and earlier)',
                    'boards': ('TP-Link TL-WDR3600 v1',),
                },
            ),
            (
                'ath79-generic-tplink_tl-wdr3600-v1-squashfs-sysupgrade.bin',
                {
                    'label': 'TP-Link WDR3600 v1 (OpenWRT 19.07 and later)',
                    'boards': ('TP-Link TL-WDR3600 v1',),
                },
            ),
            (
                'ar71xx-generic-tl-wdr4300-v1-squashfs-sysupgrade.bin',
                {
                    'label': 'TP-Link WDR4300 v1 (OpenWRT 19.07 and earlier)',
                    'boards': ('TP-Link TL-WDR4300 v1',),
                },
            ),
            (
                'ath79-generic-tplink_tl-wdr4300-v1-squashfs-sysupgrade.bin',
                {
                    'label': 'TP-Link WDR4300 v1 (OpenWRT 19.07 and later)',
                    'boards': ('TP-Link TL-WDR4300 v1',),
                },
            ),
            (
                'ar71xx-generic-tl-wdr4300-v1-il-squashfs-sysupgrade.bin',
                {
                    'label': 'TP-Link WDR4300 v1 Israel Version (OpenWRT 19.07 and earlier)',
                    'boards': ('TP-LINK TL-WDR4300 v1 (IL)',),
                },
            ),
            (
                'ath79-generic-tplink_tl-wdr4300-v1-il-squashfs-sysupgrade.bin',
                {
                    'label': 'TP-Link WDR4300 v1 Israel Version (OpenWRT 19.07 and later)',
                    'boards': ('TP-LINK TL-WDR4300 v1 (IL)',),
                },
            ),
            (
                'ar71xx-generic-tl-wr2543-v1-squashfs-sysupgrade.bin',
                {
                    'label': 'TP-Link WR2543N/ND (OpenWRT 19.07 and earlier)',
                    'boards': ('TP-Link TL-WR2543N/ND',),
                },
            ),
            (
                'ath79-generic-tplink_tl-wr2543-v1-squashfs-sysupgrade.bin',
                {
                    'label': 'TP-Link WR2543N/ND (OpenWRT 19.07 and later)',
                    'boards': ('TP-Link TL-WR2543N/ND',),
                },
            ),
            (
                'ramips-mt76x8-tplink_tl-wr902ac-v3-squashfs-sysupgrade.bin',
                {
                    'label': 'TP-Link TL-WR902AC v3',
                    'boards': ('TP-Link TL-WR902AC v3',),
                },
            ),
            (
                'ar71xx-generic-ubnt-airrouter-squashfs-sysupgrade.bin',
                {
                    'label': 'Ubiquiti AirRouter (OpenWRT 19.07 and earlier)',
                    'boards': ('Ubiquiti AirRouter',),
                },
            ),
            (
                'ath79-generic-ubnt_airrouter-squashfs-sysupgrade.bin',
                {
                    'label': 'Ubiquiti AirRouter (OpenWRT 19.07 and later)',
                    'boards': ('Ubiquiti AirRouter',),
                },
            ),
            (
                'octeon-erlite-squashfs-sysupgrade.tar',
                {
                    'label': 'Ubiquiti EdgeRouter Lite',
                    'boards': ('Ubiquiti EdgeRouter Lite',),
                },
            ),
            # Nanostation Loco M XW AR71XX
            (
                'ar71xx-generic-ubnt-loco-m-xw-squashfs-sysupgrade.bin',
                {
                    'label': 'Ubiquiti Nanostation Loco M2 - XW (OpenWRT 19.07 and earlier)',
                    'boards': ('Ubiquiti Loco XW',),
                },
            ),
            # Nanostation Loco M XM ATH79
            (
                'ath79-generic-ubnt_nanostation-loco-m-squashfs-sysupgrade.bin',
                {
                    'label': 'Ubiquiti Nanostation Loco M (OpenWRT 19.07 and later)',
                    'boards': ('Ubiquiti Nanostation Loco M',),
                },
            ),
            # Nanostation Loco M XW ATH79
            (
                'ath79-generic-ubnt_nanostation-loco-m-xw-squashfs-sysupgrade.bin',
                {
                    'label': 'Ubiquiti Nanostation Loco M - XW (OpenWRT 19.07 and later)',
                    'boards': ('Ubiquiti Nanostation Loco M (XW)',),
                },
            ),
            # Nanostation M XW AR71XX
            (
                'ar71xx-generic-ubnt-nano-m-xw-squashfs-sysupgrade.bin',
                {
                    'label': 'Ubiquiti Nanostation M - XW (OpenWRT 19.07 and earlier)',
                    'boards': ('Ubiquiti Nano M XW',),
                },
            ),
            # Nanostation M XM AR71XX
            (
                'ar71xx-generic-ubnt-nano-m-squashfs-sysupgrade.bin',
                {
                    'label': 'Ubiquiti Nanostation M (OpenWRT 19.07 and earlier)',
                    'boards': (
                        'Ubiquiti Nano-M',
                        'Ubiquiti NanoStation M2',
                        'Ubiquiti NanoStation M5',
                        'Ubiquiti NanoStation loco M2',
                        'Ubiquiti NanoStation loco M5',
                    ),
                },
            ),
            # Nanostation M XW ATH79
            (
                'ath79-generic-ubnt_nanostation-m-xw-squashfs-sysupgrade.bin',
                {
                    'label': 'Ubiquiti Nanostation M - XW (OpenWRT 19.07 and later)',
                    'boards': (
                        'Ubiquiti Nanostation M (XW)',
                        'Ubiquiti Nanostation M XW',
                    ),
                },
            ),
            # Nanostation M XM ATH79
            (
                'ath79-generic-ubnt_nanostation-m-squashfs-sysupgrade.bin',
                {
                    'label': 'Ubiquiti Nanostation M (OpenWRT 19.07 and later)',
                    'boards': ('Ubiquiti Nanostation M',),
                },
            ),
            # Bullet XW AR71XX
            (
                'ar71xx-generic-ubnt-bullet-m-xw-squashfs-sysupgrade.bin',
                {
                    'label': 'Ubiquiti Picostation Bullet XW (OpenWRT 19.07 and earlier)',
                    'boards': ('Ubiquiti Bullet-M XW',),
                },
            ),
            # Picostation M2HP & Bullet AR71XX
            (
                'ar71xx-generic-ubnt-bullet-m-squashfs-sysupgrade.bin',
                {
                    'label': 'Ubiquiti Picostation M2HP & Bullet (OpenWRT 19.07 and earlier)',
                    'boards': (
                        'Ubiquiti Bullet-M',
                        'Ubiquiti PicoStation M2',
                        'Ubiquiti PicoStation M2HP',
                    ),
                },
            ),
            # Picostation M ATH79
            (
                'ath79-generic-ubnt_picostation-m-squashfs-sysupgrade.bin',
                {
                    'label': 'Ubiquiti Picostation M (OpenWRT 19.07 and later)',
                    'boards': ('Ubiquiti Picostation M',),
                },
            ),
            # Unifi AC Mesh AR71XX
            (
                'ar71xx-generic-ubnt-unifiac-mesh-squashfs-sysupgrade.bin',
                {
                    'label': 'Ubiquiti Unifi AC Mesh (OpenWRT 19.07 and earlier)',
                    'boards': (
                        'Ubiquiti UniFi AC-Mesh',
                        'Ubiquiti UniFi-AC-MESH',
                        'Ubiquiti UniFi-AC-LITE/MESH',
                    ),
                },
            ),
            # Unifi AC Mesh ATH79
            (
                'ath79-generic-ubnt_unifiac-mesh-squashfs-sysupgrade.bin',
                {
                    'label': 'Ubiquiti Unifi AC Mesh (OpenWRT 19.07 and later)',
                    'boards': (
                        'Ubiquiti UniFi AC Mesh',
                        'Ubiquiti UniFi AC-Mesh',
                        'Ubiquiti UniFi-AC-MESH',
                        'Ubiquiti UniFi-AC-LITE/MESH',
                    ),
                },
            ),
            # Unifi AC Mesh Pro AR71XX
            (
                'ar71xx-generic-ubnt-unifiac-mesh-pro-squashfs-sysupgrade.bin',
                {
                    'label': 'Ubiquiti Unifi AC Mesh-Pro (OpenWRT 19.07 and earlier)',
                    'boards': ('Ubiquiti UniFi AC-Mesh-Pro',),
                },
            ),
            # Unifi AC Mesh Pro ATH79
            (
                'ath79-generic-ubnt_unifiac-mesh-pro-squashfs-sysupgrade.bin',
                {
                    'label': 'Ubiquiti Unifi AC Mesh-Pro (OpenWRT 19.07 and later)',
                    'boards': ('Ubiquiti UniFi AC-Mesh Pro',),
                },
            ),
            # Unifi AC Pro ATH79
            (
                'ath79-generic-ubnt_unifiac-pro-squashfs-sysupgrade.bin',
                {
                    'label': 'Ubiquiti UniFi AC Pro (OpenWRT 19.07 and later)',
                    'boards': ('Ubiquiti UniFi AC Pro', 'Ubiquiti UniFi-AC-PRO'),
                },
            ),
            (
                'x86-64-combined-squashfs.img.gz',
                {
                    'label': 'VMware, Inc. VMware Virtual Platform',
                    'boards': ('VMware, Inc. VMware Virtual Platform',),
                },
            ),
            (
                'ar71xx-generic-xd3200-squashfs-sysupgrade.bin',
                {
                    'label': 'YunCore XD3200 (OpenWRT 19.07 and earlier)',
                    'boards': ('YunCore XD3200',),
                },
            ),
            (
                'ramips-mt7621-zbt-wg3526-16M-squashfs-sysupgrade.bin',
                {'label': 'ZBT-WG3526 (16M)', 'boards': ('ZBT-WG3526 (16M)',)},
            ),
            (
                'x86-generic-combined-squashfs.img.gz',
                {
                    'label': 'x86 32 bit (various models)',
                    'boards': ('PC Engines APU2',),
                },
            ),
            (
                'x86-geode-combined-squashfs.img.gz',
                {
                    'label': 'x86 Geode(TM) Integrated Processor by AMD',
                    'boards': ('Geode(TM) Integrated Processor by AMD PCS', 'Alix 2D2'),
                },
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
