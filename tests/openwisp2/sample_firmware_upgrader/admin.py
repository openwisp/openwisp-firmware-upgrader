from django.contrib import admin
from openwisp_firmware_upgrader.base.admin import (AbstractBatchUpgradeOperationAdmin, AbstractBuildAdmin,
                                                   AbstractCategoryAdmin)
from swapper import load_model

BatchUpgradeOperation = load_model('firmware_upgrader', 'BatchUpgradeOperation')
Build = load_model('firmware_upgrader', 'Build')
Category = load_model('firmware_upgrader', 'Category')


@admin.register(Category)
class CategoryAdmin(AbstractCategoryAdmin):
    pass


@admin.register(Build)
class BuildAdmin(AbstractBuildAdmin):
    pass


@admin.register(BatchUpgradeOperation)
class BatchUpgradeOperationAdmin(AbstractBatchUpgradeOperationAdmin):
    pass
