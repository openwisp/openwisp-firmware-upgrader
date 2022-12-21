from openwisp_firmware_upgrader.apps import FirmwareUpdaterConfig


class SampleFirmwareUpgraderConfig(FirmwareUpdaterConfig):
    name = 'openwisp2.sample_firmware_upgrader'
    label = 'sample_firmware_upgrader'
    verbose_name = 'Firmware Upgrader (custom)'
    default_auto_field = 'django.db.models.AutoField'
