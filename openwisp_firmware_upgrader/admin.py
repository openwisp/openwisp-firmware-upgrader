import logging
from datetime import timedelta

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import resolve, reverse
from django.utils.safestring import mark_safe
from django.utils.timezone import localtime
from django.utils.translation import ugettext_lazy as _
from reversion.admin import VersionAdmin

from openwisp_controller.config.admin import DeviceAdmin
from openwisp_users.multitenancy import MultitenantAdminMixin
from openwisp_utils.admin import ReadOnlyAdmin, TimeReadonlyAdminMixin

from .hardware import REVERSE_FIRMWARE_IMAGE_MAP
from .swapper import load_model

logger = logging.getLogger(__name__)
BatchUpgradeOperation = load_model('BatchUpgradeOperation')
UpgradeOperation = load_model('UpgradeOperation')
DeviceFirmware = load_model('DeviceFirmware')
FirmwareImage = load_model('FirmwareImage')


class BaseAdmin(MultitenantAdminMixin, TimeReadonlyAdminMixin, admin.ModelAdmin):
    pass


class BaseVersionAdmin(MultitenantAdminMixin, TimeReadonlyAdminMixin, VersionAdmin):
    history_latest_first = True


@admin.register(load_model('Category'))
class CategoryAdmin(BaseVersionAdmin):
    list_display = ['name', 'organization', 'created', 'modified']
    list_filter = ['organization']
    search_fields = ['name']
    save_on_top = True
    ordering = ['-name', '-created']


class FirmwareImageInline(TimeReadonlyAdminMixin, admin.StackedInline):
    model = FirmwareImage
    extra = 0

    def has_change_permission(self, request, obj=None):
        if obj:
            return False
        return True


@admin.register(load_model('Build'))
class BuildAdmin(BaseVersionAdmin):
    list_display = ['__str__', 'category', 'created', 'modified']
    search_fields = ['name']
    save_on_top = True
    select_related = ['category']
    list_filter = ['category']
    ordering = ['-created', '-version']
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
                _(
                    'Multiple mass upgrades requested but at the moment only '
                    'a single mass upgrade operation at time is supported.'
                ),
                messages.ERROR,
            )
            # returning None will display the change list page again
            return None
        upgrade_all = request.POST.get('upgrade_all')
        upgrade_related = request.POST.get('upgrade_related')
        build = queryset.first()
        # upgrade has been confirmed
        if upgrade_all or upgrade_related:
            batch = build.batch_upgrade(firmwareless=upgrade_all)
            text = _(
                'You can track the progress of this mass upgrade operation '
                'in this page. Refresh the page from time to time to check '
                'its progress.'
            )
            self.message_user(request, mark_safe(text), messages.SUCCESS)
            url = reverse(
                f'admin:{app_label}_batchupgradeoperation_change', args=[batch.pk]
            )
            return redirect(url)
        # upgrade needs to be confirmed
        result = BatchUpgradeOperation.dry_run(build=build)
        related_device_fw = result['device_firmwares']
        firmwareless_devices = result['devices']
        title = _('Confirm mass upgrade operation')
        context = self.admin_site.each_context(request)
        context.update(
            {
                'title': title,
                'related_device_fw': related_device_fw,
                'related_count': len(related_device_fw),
                'firmwareless_devices': firmwareless_devices,
                'firmwareless_count': len(firmwareless_devices),
                'build': build,
                'opts': opts,
                'action_checkbox_name': ACTION_CHECKBOX_NAME,
                'media': self.media,
            }
        )
        request.current_app = self.admin_site.name
        return TemplateResponse(
            request,
            [
                'admin/%s/%s/upgrade_selected_confirmation.html'
                % (app_label, opts.model_name),
                'admin/%s/upgrade_selected_confirmation.html' % app_label,
                'admin/upgrade_selected_confirmation.html',
            ],
            context,
        )

    upgrade_selected.short_description = (
        'Mass-upgrade devices related ' 'to the selected build'
    )


class UpgradeOperationForm(forms.ModelForm):
    class Meta:
        fields = ['device', 'image', 'status', 'log', 'modified']
        labels = {'modified': _('last updated')}


class UpgradeOperationInline(admin.StackedInline):
    model = UpgradeOperation
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


@admin.register(BatchUpgradeOperation)
class BatchUpgradeOperationAdmin(ReadOnlyAdmin, BaseAdmin):
    list_display = ['build', 'status', 'created', 'modified']
    list_filter = ['status', 'build__category']
    save_on_top = True
    select_related = ['build']
    ordering = ['-created']
    inlines = [UpgradeOperationInline]
    multitenant_parent = 'build__category'
    fields = [
        'build',
        'status',
        'completed',
        'success_rate',
        'failed_rate',
        'aborted_rate',
        'created',
        'modified',
    ]
    readonly_fields = ['completed', 'success_rate', 'failed_rate', 'aborted_rate']

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


class DeviceFirmwareForm(forms.ModelForm):
    class Meta:
        model = DeviceFirmware
        fields = '__all__'

    def _get_image_queryset(self, device):
        # restrict firmware images to organization of the current device
        qs = (
            FirmwareImage.objects.filter(
                build__category__organization_id=device.organization_id
            )
            .order_by('-created')
            .select_related('build', 'build__category')
        )
        # if device model is defined
        # restrict the images to the ones compatible with it
        if device.model and device.model in REVERSE_FIRMWARE_IMAGE_MAP:
            qs = qs.filter(type=REVERSE_FIRMWARE_IMAGE_MAP[device.model])
        # if DeviceFirmware instance already exists
        # restrict images to the ones of the same category
        if not self.instance._state.adding:
            self.instance.refresh_from_db()
            qs = qs.filter(build__category_id=self.instance.image.build.category_id)
        return qs

    def __init__(self, device, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['image'].queryset = self._get_image_queryset(device)


class DeviceFormSet(forms.BaseInlineFormSet):
    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs['device'] = self.instance
        return kwargs


class DeviceFirmwareInline(MultitenantAdminMixin, admin.StackedInline):
    model = DeviceFirmware
    formset = DeviceFormSet
    form = DeviceFirmwareForm
    exclude = ['created']
    select_related = ['device', 'image']
    readonly_fields = ['installed', 'modified']
    verbose_name = _('Firmware')
    verbose_name_plural = verbose_name
    extra = 0
    multitenant_shared_relations = ['device']


class DeviceUpgradeOperationForm(UpgradeOperationForm):
    class Meta(UpgradeOperationForm.Meta):
        pass

    def __init__(self, device, *args, **kwargs):
        self.device = device
        super().__init__(*args, **kwargs)


class DeviceUpgradeOperationInline(UpgradeOperationInline):
    verbose_name = _('Recent Firmware Upgrades')
    verbose_name_plural = verbose_name
    formset = DeviceFormSet
    form = DeviceUpgradeOperationForm

    def get_queryset(self, request, select_related=True):
        """
        Return recent upgrade operations for this device
        (created within the last 7 days)
        """
        qs = super().get_queryset(request)
        resolved = resolve(request.path_info)
        if 'object_id' in resolved.kwargs:
            seven_days = localtime() - timedelta(days=7)
            qs = qs.filter(
                device_id=resolved.kwargs['object_id'], created__gte=seven_days
            ).order_by('-created')
        if select_related:
            qs = qs.select_related()
        return qs


def device_admin_get_inlines(self, request, obj):
    # copy the list to avoid modifying the original data structure
    inlines = self.inlines
    if obj:
        inlines = list(inlines)  # copy
        inlines.append(DeviceFirmwareInline)
        if (
            DeviceUpgradeOperationInline(UpgradeOperation, admin.site)
            .get_queryset(request, select_related=False)
            .exists()
        ):
            inlines.append(DeviceUpgradeOperationInline)
        return inlines
    return inlines


DeviceAdmin.get_inlines = device_admin_get_inlines
