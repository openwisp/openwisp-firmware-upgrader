from django.contrib import admin
from django.utils.translation import ugettext_lazy as _

from openwisp_controller.config.admin import DeviceAdmin
from openwisp_utils.admin import TimeReadonlyAdminMixin

from .models import Build, Category, DeviceFirmware, FirmwareImage


@admin.register(Category)
class CategoryAdmin(TimeReadonlyAdminMixin, admin.ModelAdmin):
    list_display = ('name', 'created', 'modified')
    search_fields = ['name']
    save_on_top = True


class FirmwareImageInline(TimeReadonlyAdminMixin, admin.StackedInline):
    model = FirmwareImage
    extra = 0


@admin.register(Build)
class BuildAdmin(TimeReadonlyAdminMixin, admin.ModelAdmin):
    list_display = ('category', 'version', 'created', 'modified')
    search_fields = ['name']
    save_on_top = True
    select_related = ('category',)
    ordering = ('-version',)
    inlines = [FirmwareImageInline]


class DeviceFirmwareInline(admin.StackedInline):
    model = DeviceFirmware
    exclude = ('created',)
    readonly_fields = ('installed', 'modified')
    verbose_name = _('Device Firmware')
    verbose_name_plural = verbose_name


DeviceAdmin.inlines.append(DeviceFirmwareInline)
