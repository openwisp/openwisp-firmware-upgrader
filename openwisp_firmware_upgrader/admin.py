import logging

from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.template.response import TemplateResponse
from django.utils.translation import ugettext_lazy as _

from openwisp_controller.config.admin import DeviceAdmin
from openwisp_users.multitenancy import MultitenantAdminMixin
from openwisp_utils.admin import TimeReadonlyAdminMixin

from .models import Build, Category, DeviceFirmware, FirmwareImage, batch_upgrade_operation

logger = logging.getLogger(__name__)


@admin.register(Category)
class CategoryAdmin(MultitenantAdminMixin, TimeReadonlyAdminMixin, admin.ModelAdmin):
    list_display = ('name', 'created', 'modified')
    search_fields = ['name']
    save_on_top = True


class FirmwareImageInline(TimeReadonlyAdminMixin, admin.StackedInline):
    model = FirmwareImage
    extra = 0


@admin.register(Build)
class BuildAdmin(MultitenantAdminMixin, TimeReadonlyAdminMixin, admin.ModelAdmin):
    list_display = ('__str__', 'created', 'modified')
    search_fields = ['name']
    save_on_top = True
    select_related = ('category',)
    ordering = ('-version',)
    inlines = [FirmwareImageInline]
    actions = ['upgrade_selected']

    multitenant_shared_relations = ('category',)

    def upgrade_selected(self, request, queryset):
        opts = self.model._meta
        app_label = opts.app_label
        # multiple concurrent batch upgrades are not supported
        if queryset.count() > 1:
            self.message_user(
                request,
                _('Multiple batch upgrades requested but at the moment only '
                  'a single batch upgrade operation at time is supported.'),
                messages.ERROR
            )
            # returning None will display the change list page again
            return None
        upgrade_all = request.POST.get('upgrade_all')
        upgrade_related = request.POST.get('upgrade_related')
        build = queryset.first()
        # upgrade has been confirmed
        if upgrade_all or upgrade_related:
            self.message_user(
                request,
                _('Batch upgrade operation started'),
                messages.SUCCESS
            )
            batch_upgrade_operation.delay(build_id=build.pk,
                                          firmwareless=upgrade_all)
            # returning None will display the change list page again
            return None
        # upgrade needs to be confirmed
        related_device_fw = build._find_related_device_firmwares(select_devices=True)
        firmwareless_devices = build._find_firmwareless_devices()
        title = _('Confirm batch upgrade operation')
        context = self.admin_site.each_context(request)
        context.update({
            'title': title,
            'related_device_fw': related_device_fw,
            'related_count': len(related_device_fw),
            'firmwareless_devices': firmwareless_devices,
            'firmwareless_count': len(firmwareless_devices),
            'build': build,
            'opts': opts,
            'action_checkbox_name': ACTION_CHECKBOX_NAME,
            'media': self.media,
        })
        request.current_app = self.admin_site.name
        return TemplateResponse(request, [
            'admin/%s/%s/upgrade_selected_confirmation.html' % (app_label, opts.model_name),
            'admin/%s/upgrade_selected_confirmation.html' % app_label,
            'admin/upgrade_selected_confirmation.html'
        ], context)

    upgrade_selected.short_description = 'Upgrade devices of the selected build'


class DeviceFirmwareInline(MultitenantAdminMixin, admin.StackedInline):
    model = DeviceFirmware
    exclude = ('created',)
    readonly_fields = ('installed', 'modified')
    verbose_name = _('Device Firmware')
    verbose_name_plural = verbose_name
    extra = 0

    multitenant_shared_relations = ('image',)


DeviceAdmin.inlines.append(DeviceFirmwareInline)
