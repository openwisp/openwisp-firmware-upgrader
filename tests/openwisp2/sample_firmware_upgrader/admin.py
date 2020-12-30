from openwisp_firmware_upgrader.admin import (  # noqa
    BatchUpgradeOperationAdmin,
    BuildAdmin,
    CategoryAdmin,
    UpgradeOperationForm,
)

BatchUpgradeOperationAdmin.fields.append('details')
UpgradeOperationForm.Meta.fields.append('details')
