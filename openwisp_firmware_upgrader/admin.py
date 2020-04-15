from django.contrib import admin

from .base.admin import (
    AbstractBatchUpgradeOperationAdmin,
    AbstractBuildAdmin,
    AbstractCategoryAdmin,
)
from .models import BatchUpgradeOperation, Build, Category


@admin.register(Category)
class CategoryAdmin(AbstractCategoryAdmin):
    pass


@admin.register(Build)
class BuildAdmin(AbstractBuildAdmin):
    pass


@admin.register(BatchUpgradeOperation)
class BatchUpgradeOperationAdmin(AbstractBatchUpgradeOperationAdmin):
    pass
