from openwisp_firmware_upgrader.admin import (  # noqa
    BatchUpgradeOperationAdmin,
    BuildAdmin,
    CategoryAdmin,
    DeviceFirmwareInline,
    DeviceUpgradeOperationInline,
    FirmwareImageAdmin,
    FirmwareImageInline,
    UpgradeOperationForm,
)

BatchUpgradeOperationAdmin.fields.append("details")
UpgradeOperationForm.Meta.fields.append("details")
DeviceUpgradeOperationInline.fields.append("details")
DeviceFirmwareInline.fields.append("details")
BuildAdmin.fieldsets[0][1]["fields"].append("details")
FirmwareImageInline.fields.append("details")
FirmwareImageAdmin.fieldsets[0][1]["fields"].append("details")
