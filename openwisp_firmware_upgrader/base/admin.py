import logging

from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _
from reversion.admin import VersionAdmin
from swapper import load_model

from openwisp_controller.config.admin import DeviceAdmin
from openwisp_users.multitenancy import MultitenantAdminMixin
from openwisp_utils.admin import ReadOnlyAdmin, TimeReadonlyAdminMixin

from ..tasks import batch_upgrade_operation
from .forms import UpgradeOperationForm

logger = logging.getLogger(__name__)


class BaseAdmin(MultitenantAdminMixin, TimeReadonlyAdminMixin, admin.ModelAdmin):
    pass


class BaseVersionAdmin(MultitenantAdminMixin, TimeReadonlyAdminMixin, VersionAdmin):
    history_latest_first = True


class AbstractCategoryAdmin(BaseVersionAdmin):
    list_display = ('name', 'organization', 'created', 'modified')
    list_filter = ('organization',)
    search_fields = ['name']
    save_on_top = True


class FirmwareImageInline(TimeReadonlyAdminMixin, admin.StackedInline):
    model = load_model('firmware_upgrader', 'FirmwareImage')
    extra = 0


class AbstractBuildAdmin(BaseVersionAdmin):
    list_display = ('__str__', 'category', 'created', 'modified')
    search_fields = ['name']
    save_on_top = True
    select_related = ('category',)
    list_filter = ('category',)
    ordering = ('-version',)
    inlines = [FirmwareImageInline]
    actions = ['upgrade_selected']
    multitenant_parent = 'category'

    def upgrade_selected(self, request, queryset):
        opts = self.model._meta
        app_label = opts.app_label
        # multiple concurrent batch upgrades are not supported
        # (it's not yet possible to select more builds and upgrade
        #  all of them at the same time)
        if queryset.count() > 1:
            self.message_user(
                request,
                _('Multiple mass upgrades requested but at the moment only '
                  'a single mass upgrade operation at time is supported.'),
                messages.ERROR
            )
            # returning None will display the change list page again
            return None
        upgrade_all = request.POST.get('upgrade_all')
        upgrade_related = request.POST.get('upgrade_related')
        build = queryset.first()
        url = reverse(f'admin:{app_label}_batchupgradeoperation_changelist')
        # upgrade has been confirmed
        if upgrade_all or upgrade_related:
            from django.utils.safestring import mark_safe
            text = _('Mass upgrade operation started, you can '
                     'track its progress from the <a href="%s">list '
                     'of mass upgrades</a>.') % url
            self.message_user(request, mark_safe(text), messages.SUCCESS)
            batch_upgrade_operation.delay(build_id=build.pk,
                                          firmwareless=upgrade_all)
            # returning None will display the change list page again
            return None
        # upgrade needs to be confirmed
        related_device_fw = build._find_related_device_firmwares(select_devices=True)
        firmwareless_devices = build._find_firmwareless_devices()
        title = _('Confirm mass upgrade operation')
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

    upgrade_selected.short_description = 'Mass-upgrade devices related ' \
                                         'to the selected build'


class UpgradeOperationInline(admin.StackedInline):
    model = load_model('firmware_upgrader', 'UpgradeOperation')
    form = UpgradeOperationForm
    readonly_fields = UpgradeOperationForm.Meta.fields
    extra = 0

    def last_updated(self, obj):
        return obj.modified

    last_updated.short_description = _('last updated at')

    def has_delete_permission(self, request, obj):
        return False

    def has_add_permission(self, request, obj):
        return False


class AbstractBatchUpgradeOperationAdmin(ReadOnlyAdmin, BaseAdmin):
    list_display = ('build', 'status', 'created', 'modified')
    list_filter = ('status', 'build__category')
    save_on_top = True
    select_related = ('build',)
    ordering = ('-created',)
    inlines = [UpgradeOperationInline]
    multitenant_parent = 'build'
    fields = [
        'build',
        'status',
        'completed',
        'success_rate',
        'failed_rate',
        'aborted_rate',
        'created',
        'modified'
    ]
    readonly_fields = [
        'completed',
        'success_rate',
        'failed_rate',
        'aborted_rate'
    ]

    def get_readonly_fields(self, request, obj):
        fields = super().get_readonly_fields(request, obj)
        return fields + self.__class__.readonly_fields

    def completed(self, obj):
        return obj.progress_report

    def success_rate(self, obj):
        return self.__get_rate(obj.success_rate)

    def failed_rate(self, obj):
        return self.__get_rate(obj.failed_rate)

    def aborted_rate(self, obj):
        return self.__get_rate(obj.aborted_rate)

    def __get_rate(self, value):
        if value:
            return f'{value}%'
        return 'N/A'

    completed.short_description = _('completed')
    success_rate.short_description = _('success rate')
    failed_rate.short_description = _('failure rate')
    aborted_rate.short_description = _('abortion rate')


class DeviceFirmwareInline(MultitenantAdminMixin, admin.StackedInline):
    model = load_model('firmware_upgrader', 'DeviceFirmware')
    exclude = ('created',)
    readonly_fields = ('installed', 'modified')
    verbose_name = _('Device Firmware')
    verbose_name_plural = verbose_name
    extra = 0
    multitenant_shared_relations = ('image',)

    def has_add_permission(self, request, obj=None):
        return obj and not obj._state.adding


DeviceAdmin.inlines.append(DeviceFirmwareInline)
