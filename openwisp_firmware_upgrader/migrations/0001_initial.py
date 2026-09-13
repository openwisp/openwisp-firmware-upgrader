import uuid

import django.db.models.deletion
import django.utils.timezone
import model_utils.fields
import swapper
from django.conf import settings
from django.db import migrations, models
from swapper import dependency, split

import openwisp_users.mixins

from ..swapper import get_model_name

FIRMWARE_IMAGE_TYPE_CHOICES = [
    (
        "ar71xx-generic-cf-e320n-v2-squashfs-sysupgrade.bin",
        "COMFAST CF-E320N v2 (OpenWrt 19.07 and earlier)",
    ),
    ("ath79-generic-comfast_cf-e375ac-squashfs-sysupgrade.bin", "COMFAST CF-E375AC"),
    (
        "dongwon_dw02-412h-128m-squashfs-sysupgrade.bin",
        "Dongwon T&I DW02-412H (128M) / KT GiGA WiFi home (128M)",
    ),
    ("ipq807x-generic-edgecore_eap102-squashfs-sysupgrade.bin", "Edgecore EAP102"),
    ("ipq40xx-generic-engenius_eap1300-squashfs-sysupgrade.bin", "EnGenius EAP1300"),
    ("realtek-rtl838x-engenius_ews2910p-squashfs-sysupgrade.bin", "EnGenius EWS2910P"),
    (
        "mpc85xx-p1020-extreme-networks_ws-ap3825i-squashfs-sysupgrade.bin",
        "Extreme Networks WS-AP3825i",
    ),
    (
        "ath79-nand-glinet_gl-ar300m-nand-squashfs-sysupgrade.bin",
        "GL.iNet GL-AR300M (NAND)",
    ),
    ("ramips-mt76x8-gl-mt300n-v2-squashfs-sysupgrade.bin", "GL.iNet GL-MT300N-V2"),
    ("ipq40xx-chromium-google_wifi-squashfs-sysupgrade.bin", "Google WiFi (Gale)"),
    ("mvebu-cortexa9-linksys_wrt1900acs-squashfs-sysupgrade.img", "Linksys WRT1900ACS"),
    ("mvebu-cortexa9-linksys_wrt3200acm-squashfs-sysupgrade.img", "Linksys WRT3200ACM"),
    ("ipq40xx-mikrotik-mikrotik_wap-ac-squashfs-sysupgrade.bin", "MikroTik wAP ac"),
    (
        "ramips-mt7621-mikrotik_routerboard-m33g-squashfs-sysupgrade.bin",
        "MikroTik RouterBOARD M33G",
    ),
    ("mediatek-filogic-netgear_wax220-squashfs-sysupgrade.bin", "Netgear WAX220"),
    ("ath79-generic-netgear_wndap360-squashfs-sysupgrade.bin", "Netgear WNDAP360"),
    ("brcm2708-bcm2709-rpi-2-ext4-sysupgrade.img.gz", "Raspberry Pi 2 Model B"),
    ("brcm2708-bcm2710-rpi-3-ext4-sysupgrade.img.gz", "Raspberry Pi 3 Model B"),
    (
        "ramips-mt7621-tplink_archer-ax23-v1-squashfs-sysupgrade.bin",
        "TP-Link Archer AX23 v1",
    ),
    (
        "ar71xx-generic-archer-c7-v1-squashfs-sysupgrade.bin",
        "TP-Link Archer C7 v1 (OpenWrt 19.07 and earlier)",
    ),
    (
        "ath79-generic-tplink_archer-c7-v1-squashfs-sysupgrade.bin",
        "TP-Link Archer C7 v1 (OpenWrt 19.07 and later)",
    ),
    (
        "ar71xx-generic-archer-c7-v2-squashfs-sysupgrade.bin",
        "TP-Link Archer C7 v2 (OpenWrt 19.07 and earlier)",
    ),
    (
        "ath79-generic-tplink_archer-c7-v2-squashfs-sysupgrade.bin",
        "TP-Link Archer C7 v2 (OpenWrt 19.07 and later)",
    ),
    (
        "ar71xx-generic-archer-c7-v4-squashfs-sysupgrade.bin",
        "TP-Link Archer C7 v4 (OpenWrt 19.07 and earlier)",
    ),
    (
        "ath79-generic-tplink_archer-c7-v4-squashfs-sysupgrade.bin",
        "TP-Link Archer C7 v4 (OpenWrt 19.07 and later)",
    ),
    (
        "ar71xx-generic-archer-c7-v5-squashfs-sysupgrade.bin",
        "TP-Link Archer C7 v5 (OpenWrt 19.07 and earlier)",
    ),
    (
        "ath79-generic-tplink_archer-c7-v5-squashfs-sysupgrade.bin",
        "TP-Link Archer C7 v5 (OpenWrt 19.07 and later)",
    ),
    (
        "ramips-mt76x8-tplink_archer-c50-v4-squashfs-sysupgrade.bin",
        "TP-Link Archer C50 v4",
    ),
    (
        "ar71xx-generic-cpe210-220-v1-squashfs-sysupgrade.bin",
        "TP-Link CPE210 v1 (OpenWrt 19.07 and earlier)",
    ),
    ("ath79-generic-tplink_cpe210-v2-squashfs-sysupgrade.bin", "TP-Link CPE210 v2"),
    ("ath79-generic-tplink_cpe210-v3-squashfs-sysupgrade.bin", "TP-Link CPE210 v3"),
    ("ath79-generic-tplink_cpe510-v3-squashfs-sysupgrade.bin", "TP-Link CPE510 v3"),
    (
        "ath79-generic-tplink_eap225-outdoor-v3-squashfs-sysupgrade.bin",
        "TP-Link EAP225-Outdoor v3",
    ),
    (
        "ath79-generic-tplink_tl-mr6400-v1-squashfs-sysupgrade.bin",
        "TP-Link TL-MR6400 v1",
    ),
    (
        "ramips-mt76x8-tplink_tl-mr6400-v4-squashfs-sysupgrade.bin",
        "TP-Link TL-MR6400 v4",
    ),
    (
        "ramips-mt76x8-tplink_tl-mr6400-v5-squashfs-sysupgrade.bin",
        "TP-Link TL-MR6400 v5",
    ),
    (
        "ramips-mt76x8-tplink_tl-mr6400-v7-squashfs-sysupgrade.bin",
        "TP-Link TL-MR6400 v7",
    ),
    (
        "ar71xx-generic-tl-wdr3600-v1-squashfs-sysupgrade.bin",
        "TP-Link WDR3600 v1 (OpenWrt 19.07 and earlier)",
    ),
    (
        "ath79-generic-tplink_tl-wdr3600-v1-squashfs-sysupgrade.bin",
        "TP-Link WDR3600 v1 (OpenWrt 19.07 and later)",
    ),
    (
        "ar71xx-generic-tl-wdr4300-v1-squashfs-sysupgrade.bin",
        "TP-Link WDR4300 v1 (OpenWrt 19.07 and earlier)",
    ),
    (
        "ath79-generic-tplink_tl-wdr4300-v1-squashfs-sysupgrade.bin",
        "TP-Link WDR4300 v1 (OpenWrt 19.07 and later)",
    ),
    (
        "ar71xx-generic-tl-wdr4300-v1-il-squashfs-sysupgrade.bin",
        "TP-Link WDR4300 v1 Israel Version (OpenWrt 19.07 and earlier)",
    ),
    (
        "ath79-generic-tplink_tl-wdr4300-v1-il-squashfs-sysupgrade.bin",
        "TP-Link WDR4300 v1 Israel Version (OpenWrt 19.07 and later)",
    ),
    (
        "ar71xx-generic-tl-wr2543-v1-squashfs-sysupgrade.bin",
        "TP-Link WR2543N/ND (OpenWrt 19.07 and earlier)",
    ),
    (
        "ath79-generic-tplink_tl-wr2543-v1-squashfs-sysupgrade.bin",
        "TP-Link WR2543N/ND (OpenWrt 19.07 and later)",
    ),
    (
        "ramips-mt76x8-tplink_tl-wr902ac-v3-squashfs-sysupgrade.bin",
        "TP-Link TL-WR902AC v3",
    ),
    (
        "ar71xx-generic-ubnt-airrouter-squashfs-sysupgrade.bin",
        "Ubiquiti AirRouter (OpenWrt 19.07 and earlier)",
    ),
    (
        "ath79-generic-ubnt_airrouter-squashfs-sysupgrade.bin",
        "Ubiquiti AirRouter (OpenWrt 19.07 and later)",
    ),
    (
        "octeon-generic-ubnt_edgerouter-lite-squashfs-sysupgrade.tar",
        "Ubiquiti EdgeRouter Lite",
    ),
    (
        "ar71xx-generic-ubnt-loco-m-xw-squashfs-sysupgrade.bin",
        "Ubiquiti Nanostation Loco M2 - XW (OpenWrt 19.07 and earlier)",
    ),
    (
        "ath79-generic-ubnt_nanostation-loco-m-squashfs-sysupgrade.bin",
        "Ubiquiti Nanostation Loco M (OpenWrt 19.07 and later)",
    ),
    (
        "ath79-tiny-ubnt_nanostation-loco-m-squashfs-sysupgrade.bin",
        "Ubiquiti Nanostation Loco M (OpenWrt, ath79-tiny)",
    ),
    (
        "ath79-generic-ubnt_nanostation-loco-m-xw-squashfs-sysupgrade.bin",
        "Ubiquiti Nanostation Loco M - XW (OpenWrt 19.07 and later)",
    ),
    (
        "ar71xx-generic-ubnt-nano-m-xw-squashfs-sysupgrade.bin",
        "Ubiquiti Nanostation M - XW (OpenWrt 19.07 and earlier)",
    ),
    (
        "ar71xx-generic-ubnt-nano-m-squashfs-sysupgrade.bin",
        "Ubiquiti Nanostation M (OpenWrt 19.07 and earlier)",
    ),
    (
        "ath79-generic-ubnt_nanostation-m-xw-squashfs-sysupgrade.bin",
        "Ubiquiti Nanostation M - XW (OpenWrt 19.07 and later)",
    ),
    (
        "ath79-generic-ubnt_nanostation-m-squashfs-sysupgrade.bin",
        "Ubiquiti Nanostation M (OpenWrt 19.07 and later)",
    ),
    (
        "ath79-tiny-ubnt_nanostation-m-squashfs-sysupgrade.bin",
        "Ubiquiti Nanostation M (OpenWrt ath79-tiny)",
    ),
    (
        "ar71xx-generic-ubnt-bullet-m-xw-squashfs-sysupgrade.bin",
        "Ubiquiti Picostation Bullet XW (OpenWrt 19.07 and earlier)",
    ),
    (
        "ar71xx-generic-ubnt-bullet-m-squashfs-sysupgrade.bin",
        "Ubiquiti Picostation M2HP & Bullet (OpenWrt 19.07 and earlier)",
    ),
    (
        "ath79-generic-ubnt_picostation-m-squashfs-sysupgrade.bin",
        "Ubiquiti Picostation M (OpenWrt 19.07 and later)",
    ),
    (
        "ath79-tiny-ubnt_picostation-m-squashfs-sysupgrade.bin",
        "Ubiquiti Picostation M (OpenWrt, ath79-tiny)",
    ),
    (
        "mediatek-filogic-ubnt_unifi-6-plus-squashfs-sysupgrade.bin",
        "Ubiquiti UniFi 6 Plus",
    ),
    (
        "ramips-mt7621-ubnt_unifi-6-lite-squashfs-sysupgrade.bin",
        "Ubiquiti UniFi 6 Lite",
    ),
    (
        "mediatek-mt7622-ubnt_unifi-6-lr-v1-squashfs-sysupgrade.bin",
        "Ubiquiti Unifi 6 LR v1",
    ),
    (
        "mediatek-mt7622-ubnt_unifi-6-lr-v2-squashfs-sysupgrade.bin",
        "Ubiquiti Unifi 6 LR v2",
    ),
    (
        "mediatek-mt7622-ubnt_unifi-6-lr-v3-squashfs-sysupgrade.bin",
        "Ubiquiti Unifi 6 LR v3",
    ),
    (
        "ath79-generic-ubnt_unifi-ap-squashfs-sysupgrade.bin",
        "Ubiquiti UniFi AP (OpenWRT 19.07 and later)",
    ),
    ("ath79-generic-ubnt_unifi-ap-lr-squashfs-sysupgrade.bin", "Ubiquiti UniFi AP-LR"),
    (
        "ath79-generic-ubnt_unifiac-lr-squashfs-sysupgrade.bin",
        "Ubiquiti UniFi AC-LR (OpenWrt 19.07 and later)",
    ),
    (
        "ar71xx-generic-ubnt-unifiac-mesh-squashfs-sysupgrade.bin",
        "Ubiquiti Unifi AC Mesh (OpenWrt 19.07 and earlier)",
    ),
    (
        "ath79-generic-ubnt_unifiac-mesh-squashfs-sysupgrade.bin",
        "Ubiquiti Unifi AC Mesh (OpenWrt 19.07 and later)",
    ),
    (
        "ar71xx-generic-ubnt-unifiac-mesh-pro-squashfs-sysupgrade.bin",
        "Ubiquiti Unifi AC Mesh-Pro (OpenWrt 19.07 and earlier)",
    ),
    (
        "ath79-generic-ubnt_unifiac-mesh-pro-squashfs-sysupgrade.bin",
        "Ubiquiti Unifi AC Mesh-Pro (OpenWrt 19.07 and later)",
    ),
    (
        "ath79-generic-ubnt_unifiac-pro-squashfs-sysupgrade.bin",
        "Ubiquiti UniFi AC Pro (OpenWrt 19.07 and later)",
    ),
    (
        "ath79-generic-ubnt_unifi-ap-pro-squashfs-sysupgrade.bin",
        "Ubiquiti UniFi AP Pro (OpenWrt 19.07 and later)",
    ),
    (
        "ar71xx-generic-ubnt-uap-pro-squashfs-sysupgrade.bin",
        "Ubiquiti UniFi AP Pro (OpenWrt 19.07 and earlier)",
    ),
    ("ramips-mt7621-yuncore_ax820-squashfs-sysupgrade.bin", "YunCore AX820"),
    ("ramips-mt76x8-yuncore_cpe200-squashfs-sysupgrade.bin", "YunCore CPE200"),
    ("ramips-mt7621-yuncore_g720-squashfs-sysupgrade.bin", "YunCore G720"),
    ("ramips-mt76x8-yuncore_m300-squashfs-sysupgrade.bin", "YunCore M300"),
    (
        "ar71xx-generic-xd3200-squashfs-sysupgrade.bin",
        "YunCore XD3200 (OpenWrt 19.07 and earlier)",
    ),
    (
        "ramips-mt7620-zbtlink_zbt-we1026-5g-16m-squashfs-sysupgrade.bin",
        "Zbtlink ZBT-WE1026-5G (16M)",
    ),
    (
        "ramips-mt7620-zbtlink_zbt-we826-16m-squashfs-sysupgrade.bin",
        "Zbtlink ZBT-WE826 (16M)",
    ),
    (
        "ramips-mt7620-zbtlink_zbt-we826-32m-squashfs-sysupgrade.bin",
        "Zbtlink ZBT-WE826 (32M)",
    ),
    (
        "ramips-mt7621-zbt-wg3526-16M-squashfs-sysupgrade.bin",
        "Zbtlink ZBT-WG3526 (16M)",
    ),
    (
        "ramips-mt7621-zbt-wg3526-32M-squashfs-sysupgrade.bin",
        "Zbtlink ZBT-WG3526 (32M)",
    ),
    ("x86-64-generic-squashfs-combined-efi.img.gz", "Generic x86/64 (UEFI)"),
    ("x86-64-generic-squashfs-combined.img.gz", "Generic x86/64 (BIOS)"),
    ("x86-64-combined-squashfs.img.gz", "VMware, Inc. VMware Virtual Platform"),
    ("x86-generic-generic-squashfs-combined.img.gz", "Generic x86/32 bit"),
    (
        "x86-geode-generic-squashfs-combined.img.gz",
        "x86 Geode(TM) Integrated Processor by AMD",
    ),
]


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("config", "0015_default_groups_permissions"),
        dependency(*split(settings.AUTH_USER_MODEL), version="0004_default_groups"),
        swapper.dependency("firmware_upgrader", "Category"),
        swapper.dependency("firmware_upgrader", "Build"),
        swapper.dependency("firmware_upgrader", "FirmwareImage"),
        swapper.dependency("firmware_upgrader", "DeviceFirmware"),
        swapper.dependency("firmware_upgrader", "BatchUpgradeOperation"),
        swapper.dependency("firmware_upgrader", "UpgradeOperation"),
    ]

    operations = [
        migrations.CreateModel(
            name="BatchUpgradeOperation",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("in-progress", "in progress"),
                            ("success", "completed successfully"),
                            ("failed", "completed with some failures"),
                        ],
                        default="in-progress",
                        max_length=12,
                    ),
                ),
            ],
            options={
                "swappable": swapper.swappable_setting(
                    "firmware_upgrader", "BatchUpgradeOperation"
                ),
                "verbose_name_plural": "Mass upgrade operations",
                "verbose_name": "Mass upgrade operation",
            },
        ),
        migrations.CreateModel(
            name="Build",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("version", models.CharField(db_index=True, max_length=32)),
                (
                    "changelog",
                    models.TextField(
                        blank=True,
                        help_text="descriptive text indicating what has changed since the previous version, if applicable",
                        verbose_name="change log",
                    ),
                ),
            ],
            options={
                "swappable": swapper.swappable_setting("firmware_upgrader", "Build"),
                "ordering": ("-created",),
                "verbose_name": "Firmware Build",
                "verbose_name_plural": "Firmware Builds",
            },
        ),
        migrations.CreateModel(
            name="Category",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("name", models.CharField(db_index=True, max_length=64)),
                ("description", models.TextField(blank=True)),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to=swapper.get_model_name("openwisp_users", "Organization"),
                        verbose_name="organization",
                    ),
                ),
            ],
            options={
                "swappable": swapper.swappable_setting("firmware_upgrader", "Category"),
                "verbose_name": "Firmware Category",
                "verbose_name_plural": "Firmware Categories",
            },
            bases=(openwisp_users.mixins.ValidateOrgMixin, models.Model),
        ),
        migrations.CreateModel(
            name="DeviceFirmware",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("installed", models.BooleanField(default=False)),
                (
                    "device",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        to=swapper.get_model_name("config", "Device"),
                    ),
                ),
            ],
            options={
                "swappable": swapper.swappable_setting(
                    "firmware_upgrader", "DeviceFirmware"
                ),
                "abstract": False,
                "verbose_name": "Device Firmware",
            },
        ),
        migrations.CreateModel(
            name="FirmwareImage",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("file", models.FileField(upload_to="")),
                (
                    "type",
                    models.CharField(
                        blank=True,
                        choices=FIRMWARE_IMAGE_TYPE_CHOICES,
                        help_text="firmware image type: model or architecture. Leave blank to attempt determining automatically",
                        max_length=128,
                    ),
                ),
                (
                    "build",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to=get_model_name("Build"),
                    ),
                ),
            ],
            options={
                "swappable": swapper.swappable_setting(
                    "firmware_upgrader", "FirmwareImage"
                ),
                "abstract": False,
                "verbose_name": "Firmware Image",
                "verbose_name_plural": "Firmware Images",
            },
        ),
        migrations.CreateModel(
            name="UpgradeOperation",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("in-progress", "in progress"),
                            ("success", "success"),
                            ("failed", "failed"),
                            ("aborted", "aborted"),
                        ],
                        default="in-progress",
                        max_length=12,
                    ),
                ),
                ("log", models.TextField(blank=True)),
                (
                    "batch",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        to=swapper.get_model_name(
                            "firmware_upgrader", "BatchUpgradeOperation"
                        ),
                    ),
                ),
                (
                    "device",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to=swapper.get_model_name("config", "Device"),
                    ),
                ),
                (
                    "image",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to=get_model_name("FirmwareImage"),
                    ),
                ),
            ],
            options={
                "swappable": swapper.swappable_setting(
                    "firmware_upgrader", "UpgradeOperation"
                ),
                "abstract": False,
            },
        ),
        migrations.AddField(
            model_name="devicefirmware",
            name="image",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to=get_model_name("FirmwareImage"),
            ),
        ),
        migrations.AddField(
            model_name="build",
            name="category",
            field=models.ForeignKey(
                help_text="if you have different firmware types eg: (BGP routers, wifi APs, DSL gateways) create a category for each.",
                on_delete=django.db.models.deletion.CASCADE,
                to=get_model_name("Category"),
                verbose_name="firmware category",
            ),
        ),
        migrations.AddField(
            model_name="batchupgradeoperation",
            name="build",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to=get_model_name("Build"),
            ),
        ),
        migrations.AlterUniqueTogether(
            name="firmwareimage",
            unique_together={("build", "type")},
        ),
        migrations.AlterUniqueTogether(
            name="category",
            unique_together={("name", "organization")},
        ),
        migrations.AlterUniqueTogether(
            name="build",
            unique_together={("category", "version")},
        ),
    ]
