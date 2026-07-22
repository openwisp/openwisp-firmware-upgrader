from django.db import migrations

_HARDWARE_MAP_SNAPSHOT = {
    "ar71xx-generic-cf-e320n-v2-squashfs-sysupgrade.bin": "COMFAST CF-E320N v2",
    "ath79-generic-comfast_cf-e375ac-squashfs-sysupgrade.bin": "COMFAST CF-E375AC",
    "dongwon_dw02-412h-128m-squashfs-sysupgrade.bin": "DW02-412H-128M-NAND",
    "ipq807x-generic-edgecore_eap102-squashfs-sysupgrade.bin": "Edgecore EAP102",
    "ipq40xx-generic-engenius_eap1300-squashfs-sysupgrade.bin": "EnGenius EAP1300",
    "realtek-rtl838x-engenius_ews2910p-squashfs-sysupgrade.bin": "EnGenius EWS2910P",
    "mpc85xx-p1020-extreme-networks_ws-ap3825i-squashfs-sysupgrade.bin": "Extreme Networks WS-AP3825i",
    "ath79-nand-glinet_gl-ar300m-nand-squashfs-sysupgrade.bin": "GL.iNet GL-AR300M (NAND)",
    "ramips-mt76x8-gl-mt300n-v2-squashfs-sysupgrade.bin": "GL-MT300N-V2",
    "ipq40xx-chromium-google_wifi-squashfs-sysupgrade.bin": "Google WiFi (Gale)",
    "mvebu-cortexa9-linksys_wrt1900acs-squashfs-sysupgrade.img": "Linksys WRT1900ACS",
    "mvebu-cortexa9-linksys_wrt3200acm-squashfs-sysupgrade.img": "Linksys WRT3200ACM",
    "ipq40xx-mikrotik-mikrotik_wap-ac-squashfs-sysupgrade.bin": "MikroTik wAP ac",
    "ramips-mt7621-mikrotik_routerboard-m33g-squashfs-sysupgrade.bin": "MikroTik RouterBOARD M33G",
    "mediatek-filogic-netgear_wax220-squashfs-sysupgrade.bin": "Netgear WAX220",
    "ath79-generic-netgear_wndap360-squashfs-sysupgrade.bin": "Netgear WNDAP360",
    "brcm2708-bcm2710-rpi-3-ext4-sysupgrade.img.gz": "Raspberry Pi 3 Model B Rev 1.2",
    "ramips-mt7621-tplink_archer-ax23-v1-squashfs-sysupgrade.bin": "TP-Link Archer AX23 v1",
    "ar71xx-generic-archer-c7-v1-squashfs-sysupgrade.bin": "tplink,archer-c7-v1",
    "ath79-generic-tplink_archer-c7-v1-squashfs-sysupgrade.bin": "tplink,archer-c7-v1",
    "ar71xx-generic-archer-c7-v4-squashfs-sysupgrade.bin": "TP-Link Archer C7 v4",
    "ath79-generic-tplink_archer-c7-v4-squashfs-sysupgrade.bin": "TP-Link Archer C7 v4",
    "ar71xx-generic-archer-c7-v5-squashfs-sysupgrade.bin": "TP-Link Archer C7 v5",
    "ath79-generic-tplink_archer-c7-v5-squashfs-sysupgrade.bin": "TP-Link Archer C7 v5",
    "ramips-mt76x8-tplink_archer-c50-v4-squashfs-sysupgrade.bin": "TP-Link Archer C50 v4",
    "ath79-generic-tplink_cpe210-v2-squashfs-sysupgrade.bin": "TP-Link CPE210 v2",
    "ath79-generic-tplink_cpe210-v3-squashfs-sysupgrade.bin": "TP-Link CPE210 v3",
    "ath79-generic-tplink_cpe510-v3-squashfs-sysupgrade.bin": "TP-Link CPE510 v3",
    "ath79-generic-tplink_eap225-outdoor-v3-squashfs-sysupgrade.bin": "TP-Link EAP225-Outdoor v3",
    "ath79-generic-tplink_tl-mr6400-v1-squashfs-sysupgrade.bin": "TP-Link TL-MR6400 v1",
    "ramips-mt76x8-tplink_tl-mr6400-v4-squashfs-sysupgrade.bin": "TP-Link TL-MR6400 v4",
    "ramips-mt76x8-tplink_tl-mr6400-v5-squashfs-sysupgrade.bin": "TP-Link TL-MR6400 v5",
    "ramips-mt76x8-tplink_tl-mr6400-v7-squashfs-sysupgrade.bin": "TP-Link TL-MR6400 v7",
    "ar71xx-generic-tl-wdr3600-v1-squashfs-sysupgrade.bin": "TP-Link TL-WDR3600 v1",
    "ath79-generic-tplink_tl-wdr3600-v1-squashfs-sysupgrade.bin": "TP-Link TL-WDR3600 v1",
    "ar71xx-generic-tl-wdr4300-v1-squashfs-sysupgrade.bin": "TP-Link TL-WDR4300 v1",
    "ath79-generic-tplink_tl-wdr4300-v1-squashfs-sysupgrade.bin": "TP-Link TL-WDR4300 v1",
    "ar71xx-generic-tl-wdr4300-v1-il-squashfs-sysupgrade.bin": "TP-LINK TL-WDR4300 v1 (IL)",
    "ath79-generic-tplink_tl-wdr4300-v1-il-squashfs-sysupgrade.bin": "TP-LINK TL-WDR4300 v1 (IL)",
    "ar71xx-generic-tl-wr2543-v1-squashfs-sysupgrade.bin": "TP-Link TL-WR2543N/ND",
    "ath79-generic-tplink_tl-wr2543-v1-squashfs-sysupgrade.bin": "TP-Link TL-WR2543N/ND",
    "ramips-mt76x8-tplink_tl-wr902ac-v3-squashfs-sysupgrade.bin": "TP-Link TL-WR902AC v3",
    "ar71xx-generic-ubnt-airrouter-squashfs-sysupgrade.bin": "Ubiquiti AirRouter",
    "ath79-generic-ubnt_airrouter-squashfs-sysupgrade.bin": "Ubiquiti AirRouter",
    "octeon-generic-ubnt_edgerouter-lite-squashfs-sysupgrade.tar": "Ubiquiti EdgeRouter Lite",
    "ar71xx-generic-ubnt-loco-m-xw-squashfs-sysupgrade.bin": "Ubiquiti Loco XW",
    "ath79-generic-ubnt_nanostation-loco-m-squashfs-sysupgrade.bin": "Ubiquiti Nanostation Loco M",
    "ath79-tiny-ubnt_nanostation-loco-m-squashfs-sysupgrade.bin": "Ubiquiti Nanostation Loco M (XM)",
    "ath79-generic-ubnt_nanostation-loco-m-xw-squashfs-sysupgrade.bin": "Ubiquiti Nanostation Loco M (XW)",
    "ar71xx-generic-ubnt-nano-m-xw-squashfs-sysupgrade.bin": "Ubiquiti Nano M XW",
    "ath79-generic-ubnt_nanostation-m-squashfs-sysupgrade.bin": "Ubiquiti Nanostation M",
    "ath79-tiny-ubnt_nanostation-m-squashfs-sysupgrade.bin": "Ubiquiti Nanostation M (XM)",
    "ar71xx-generic-ubnt-bullet-m-xw-squashfs-sysupgrade.bin": "Ubiquiti Bullet-M XW",
    "ath79-generic-ubnt_picostation-m-squashfs-sysupgrade.bin": "Ubiquiti Picostation M",
    "ath79-tiny-ubnt_picostation-m-squashfs-sysupgrade.bin": "Picostation M (XM)",
    "mediatek-filogic-ubnt_unifi-6-plus-squashfs-sysupgrade.bin": "Ubiquiti UniFi 6 Plus",
    "ramips-mt7621-ubnt_unifi-6-lite-squashfs-sysupgrade.bin": "Ubiquiti UniFi 6 Lite",
    "mediatek-mt7622-ubnt_unifi-6-lr-v1-squashfs-sysupgrade.bin": "Ubiquiti UniFi 6 LR v1",
    "mediatek-mt7622-ubnt_unifi-6-lr-v2-squashfs-sysupgrade.bin": "Ubiquiti UniFi 6 LR v2",
    "mediatek-mt7622-ubnt_unifi-6-lr-v3-squashfs-sysupgrade.bin": "Ubiquiti UniFi 6 LR v3",
    "ath79-generic-ubnt_unifiac-lr-squashfs-sysupgrade.bin": "Ubiquiti UniFi AC LR",
    "ar71xx-generic-ubnt-unifiac-mesh-pro-squashfs-sysupgrade.bin": "Ubiquiti UniFi AC-Mesh-Pro",
    "ath79-generic-ubnt_unifiac-mesh-pro-squashfs-sysupgrade.bin": "Ubiquiti UniFi AC-Mesh Pro",
    "ath79-generic-ubnt_unifi-ap-pro-squashfs-sysupgrade.bin": "Ubiquiti UniFi AP Pro",
    "ar71xx-generic-ubnt-uap-pro-squashfs-sysupgrade.bin": "Ubiquiti UAP Pro",
    "ramips-mt7621-yuncore_ax820-squashfs-sysupgrade.bin": "YunCore AX820",
    "ramips-mt76x8-yuncore_cpe200-squashfs-sysupgrade.bin": "Yuncore CPE200",
    "ramips-mt7621-yuncore_g720-squashfs-sysupgrade.bin": "YunCore G720",
    "ramips-mt76x8-yuncore_m300-squashfs-sysupgrade.bin": "Yuncore M300",
    "ar71xx-generic-xd3200-squashfs-sysupgrade.bin": "YunCore XD3200",
    "ramips-mt7620-zbtlink_zbt-we1026-5g-16m-squashfs-sysupgrade.bin": "Zbtlink ZBT-WE1026-5G (16M)",
    "ramips-mt7620-zbtlink_zbt-we826-16m-squashfs-sysupgrade.bin": "Zbtlink ZBT-WE826 (16M)",
    "ramips-mt7620-zbtlink_zbt-we826-32m-squashfs-sysupgrade.bin": "Zbtlink ZBT-WE826 (32M)",
    "x86-64-generic-squashfs-combined-efi.img.gz": "x86_64_efi",
    "x86-64-combined-squashfs.img.gz": "VMware, Inc. VMware Virtual Platform",
    "x86-generic-generic-squashfs-combined.img.gz": "x86",
}

_MULTI_BOARD_TYPES = {
    "brcm2708-bcm2709-rpi-2-ext4-sysupgrade.img.gz": [
        "Raspberry Pi 2 Model B Rev 1.0",
        "Raspberry Pi 2 Model B Rev 1.1",
        "Raspberry Pi 2 Model B Rev 1.2",
    ],
    "ar71xx-generic-archer-c7-v2-squashfs-sysupgrade.bin": [
        "TP-Link Archer C7 v2",
        "TP-Link Archer C7 v3",
    ],
    "ath79-generic-tplink_archer-c7-v2-squashfs-sysupgrade.bin": [
        "TP-Link Archer C7 v2",
        "TP-Link Archer C7 v3",
    ],
    "ar71xx-generic-cpe210-220-v1-squashfs-sysupgrade.bin": [
        "TP-Link CPE210 v1",
        "TP-LINK CPE220 v1",
    ],
    "ar71xx-generic-ubnt-nano-m-squashfs-sysupgrade.bin": [
        "Ubiquiti Nano-M",
        "Ubiquiti NanoStation M2",
        "Ubiquiti NanoStation M5",
        "Ubiquiti NanoStation loco M2",
        "Ubiquiti NanoStation loco M5",
    ],
    "ath79-generic-ubnt_nanostation-m-xw-squashfs-sysupgrade.bin": [
        "Ubiquiti Nanostation M (XW)",
        "Ubiquiti Nanostation M XW",
    ],
    "ar71xx-generic-ubnt-bullet-m-squashfs-sysupgrade.bin": [
        "Ubiquiti Bullet-M",
        "Ubiquiti PicoStation M2",
        "Ubiquiti PicoStation M2HP",
    ],
    "ath79-generic-ubnt_unifi-ap-squashfs-sysupgrade.bin": [
        "Ubiquiti UniFi",
        "Ubiquiti UniFi AP",
    ],
    "ath79-generic-ubnt_unifi-ap-lr-squashfs-sysupgrade.bin": [
        "Ubiquiti UniFi",
        "Ubiquiti UniFi AP LR",
    ],
    "ar71xx-generic-ubnt-unifiac-mesh-squashfs-sysupgrade.bin": [
        "Ubiquiti UniFi AC-Mesh",
        "Ubiquiti UniFi-AC-MESH",
        "Ubiquiti UniFi-AC-LITE/MESH",
    ],
    "ath79-generic-ubnt_unifiac-mesh-squashfs-sysupgrade.bin": [
        "Ubiquiti UniFi AC Mesh",
        "Ubiquiti UniFi AC-Mesh",
        "Ubiquiti UniFi-AC-MESH",
        "Ubiquiti UniFi-AC-LITE/MESH",
    ],
    "ath79-generic-ubnt_unifiac-pro-squashfs-sysupgrade.bin": [
        "Ubiquiti UniFi AC Pro",
        "Ubiquiti UniFi-AC-PRO",
    ],
    "x86-64-generic-squashfs-combined.img.gz": [
        "x86_64",
        "PC Engines APU2",
        "PC Engines apu2",
        "PC Engines apu6",
    ],
    "x86-geode-generic-squashfs-combined.img.gz": [
        "Geode(TM) Integrated Processor by AMD PCS",
        "Alix 2D2",
    ],
    "ramips-mt7621-zbt-wg3526-16M-squashfs-sysupgrade.bin": [
        "ZBT-WG3526 (16M)",
        "Zbtlink ZBT-WG3526 (16M)",
    ],
    "ramips-mt7621-zbt-wg3526-32M-squashfs-sysupgrade.bin": [
        "ZBT-WG3526 (32M)",
        "Zbtlink ZBT-WG3526 (32M)",
    ],
}


def backfill_board_from_hardware_map(apps, schema_editor):
    FirmwareImage = apps.get_model("firmware_upgrader", "FirmwareImage")
    for image_type, board in _HARDWARE_MAP_SNAPSHOT.items():
        FirmwareImage.objects.filter(
            type=image_type,
            board="",
        ).update(board=board, source="hardware map")

    for image_type, boards in _MULTI_BOARD_TYPES.items():
        boards_str = ", ".join(boards)
        log_suffix = (
            "\n[!] Board could not be set automatically, this image is compatible "
            f"with multiple boards: {boards_str}. "
            "Please set the board field manually to match your devices."
        )
        for image in FirmwareImage.objects.filter(type=image_type, board=""):
            image.extraction_log = (image.extraction_log or "") + log_suffix
            image.save(update_fields=["extraction_log"])


class Migration(migrations.Migration):
    dependencies = [
        ("firmware_upgrader", "0022_alter_firmwareimage_compatible"),
    ]
    operations = [
        migrations.RunPython(
            backfill_board_from_hardware_map,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
