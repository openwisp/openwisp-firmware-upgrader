import json
import logging
from datetime import timedelta

import reversion
import swapper
from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.core.serializers.json import DjangoJSONEncoder
from django.http.response import JsonResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.templatetags.static import static
from django.urls import path, resolve, reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.timezone import localtime
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _
from reversion.admin import VersionAdmin

from openwisp_controller.config.admin import DeviceAdmin
from openwisp_users.multitenancy import MultitenantAdminMixin, MultitenantOrgFilter
from openwisp_utils.admin import ReadOnlyAdmin, TimeReadonlyAdminMixin

from .filters import (
    BuildCategoryFilter,
    BuildCategoryOrganizationFilter,
    CategoryFilter,
    CategoryOrganizationFilter,
)
from .hardware import REVERSE_FIRMWARE_IMAGE_MAP
from .swapper import load_model
from .upgraders.openwisp import OpenWrt
from .widgets import FirmwareSchemaWidget

logger = logging.getLogger(__name__)
BatchUpgradeOperation = load_model('BatchUpgradeOperation')
UpgradeOperation = load_model('UpgradeOperation')
DeviceFirmware = load_model('DeviceFirmware')
FirmwareImage = load_model('FirmwareImage')
Category = load_model('Category')
Build = load_model('Build')
Device = swapper.load_model('config', 'Device')


class BaseAdmin(MultitenantAdminMixin, TimeReadonlyAdminMixin, admin.ModelAdmin):
    save_on_top = True


class BaseVersionAdmin(MultitenantAdminMixin, TimeReadonlyAdminMixin, VersionAdmin):
    history_latest_first = True
    save_on_top = True


@admin.register(load_model('Category'))
class CategoryAdmin(BaseVersionAdmin):
    list_display = ['name', 'organization', 'created', 'modified']
    list_filter = [MultitenantOrgFilter]
    list_select_related = ['organization']
    search_fields = ['name']
    ordering = ['-name', '-created']


class FirmwareImageInline(TimeReadonlyAdminMixin, admin.StackedInline):
    model = FirmwareImage
    extra = 0

    class Media:
        extra = '' if getattr(settings, 'DEBUG', False) else '.min'
        i18n_name = admin.widgets.SELECT2_TRANSLATIONS.get(get_language())
        i18n_file = (
            ('admin/js/vendor/select2/i18n/%s.js' % i18n_name,) if i18n_name else ()
        )
        js = (
            (
                'admin/js/vendor/jquery/jquery%s.js' % extra,
                'admin/js/vendor/select2/select2.full%s.js' % extra,
            )
            + i18n_file
            + ('admin/js/jquery.init.js', 'firmware-upgrader/js/build.js')
        )

        css = {
            'screen': ('admin/css/vendor/select2/select2%s.css' % extra,),
        }

    def has_change_permission(self, request, obj=None):
        if obj:
            return False
        return True


@admin.register(load_model('Build'))
class BuildAdmin(BaseAdmin):
    list_display = ['__str__', 'organization', 'category', 'created', 'modified']
    list_filter = [CategoryOrganizationFilter, CategoryFilter]
    list_select_related = ['category', 'category__organization']
    search_fields = ['category__name', 'version', 'os']
    ordering = ['-created', '-version']
    inlines = [FirmwareImageInline]
    actions = ['upgrade_selected']
    multitenant_parent = 'category'
    autocomplete_fields = ['category']

    # Allows apps that extend this modules to use this template with less hacks
    change_form_template = 'admin/firmware_upgrader/change_form.html'

    def organization(self, obj):
        return obj.category.organization

    organization.short_description = _('organization')

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

    def change_view(self, request, object_id, form_url='', extra_context=None):
        app_label = self.model._meta.app_label
        extra_context = extra_context or {}
        upgrade_url = f'{app_label}_build_changelist'
        extra_context.update({'upgrade_url': upgrade_url})
        return super().change_view(request, object_id, form_url, extra_context)


class UpgradeOperationForm(forms.ModelForm):
    class Meta:
        fields = ['device', 'image', 'status', 'log', 'modified', 'upgrade_options']
        labels = {'modified': _('last updated')}


class UpgradeOperationInline(admin.StackedInline):
    model = UpgradeOperation
    form = UpgradeOperationForm
    readonly_fields = UpgradeOperationForm.Meta.fields
    extra = 0

    def has_delete_permission(self, request, obj):
        return False

    def has_add_permission(self, request, obj):
        return False


@admin.register(BatchUpgradeOperation)
class BatchUpgradeOperationAdmin(ReadOnlyAdmin, BaseAdmin):
    list_display = ['build', 'organization', 'status', 'created', 'modified']
    list_filter = [
        BuildCategoryOrganizationFilter,
        'status',
        BuildCategoryFilter,
    ]
    list_select_related = ['build__category__organization']
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
    autocomplete_fields = ['build']
    readonly_fields = ['completed', 'success_rate', 'failed_rate', 'aborted_rate']

    def organization(self, obj):
        return obj.build.category.organization

    organization.short_description = _('organization')

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
    upgrade_options = forms.JSONField(widget=FirmwareSchemaWidget, required=False)

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

    def save(self, commit=True):
        """
        Adapted from ModelForm.save()

        Passes "upgrade_options to DeviceFirmware.save()
        """
        if self.errors:
            raise ValueError(
                "The %s could not be %s because the data didn't validate."
                % (
                    self.instance._meta.object_name,
                    'created' if self.instance._state.adding else 'changed',
                )
            )
        if commit:
            # If committing, save the instance and the m2m data immediately.
            self.instance.save(upgrade_options=self.cleaned_data['upgrade_options'])
            self._save_m2m()
        else:
            # If not committing, add a method to the form to allow deferred
            # saving of m2m data.
            self.save_m2m = self._save_m2m
        return self.instance


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
    template = 'admin/firmware_upgrader/device_firmware_inline.html'
    # hack for openwisp-monitoring integartion
    # TODO: remove when this issue solved:
    # https://github.com/theatlantic/django-nested-admin/issues/128#issuecomment-665833142
    sortable_options = {'disabled': True}

    def _get_conditional_queryset(self, request, obj, select_related=False):
        return bool(obj)

    def get_urls(self):
        options = self.model._meta
        url_prefix = f'{options.app_label}_{options.model_name}'
        return [
            path(
                f'{options.app_label}/{options.model_name}/ui/schema.json',
                self.admin_site.admin_view(self.schema_view),
                name=f'{url_prefix}_schema',
            ),
        ]

    def schema_view(self, request):
        return JsonResponse(OpenWrt.SCHEMA)

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj=obj, **kwargs)
        # TODO: The OpenWrt schema is hard coded here. We need to find
        # a way to dynamically select schema of the appropriate upgrader.
        formset.extra_context = json.dumps(OpenWrt.SCHEMA, cls=DjangoJSONEncoder)
        return formset


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
    # hack for openwisp-monitoring integration
    # TODO: remove when this issue solved:
    # https://github.com/theatlantic/django-nested-admin/issues/128#issuecomment-665833142
    sortable_options = {'disabled': True}
    fields = [
        'device',
        'image',
        'status',
        'log',
        'readonly_upgrade_options',
        'modified',
    ]
    readonly_fields = fields

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

    def _get_conditional_queryset(self, request, obj, select_related=False):
        if obj:
            return self.get_queryset(request, select_related=False).exists()
        return False

    @admin.display(description=_('Upgrade options'))
    def readonly_upgrade_options(self, obj):
        # TODO: The OpenWrt schema is hard coded here. We need to find
        # a way to dynamically select schema of the appropriate upgrader.
        options = []
        for key, value in OpenWrt.SCHEMA['properties'].items():
            option_used = 'yes' if obj.upgrade_options.get(key, False) else 'no'
            option_title = value['title']
            icon_url = static(f'admin/img/icon-{option_used}.svg')
            options.append(
                f'<li><img src="{icon_url}" ' f'alt="{option_used}">{option_title}</li>'
            )
        return format_html(
            mark_safe(f'<ul class="readonly-upgrade-options">{"".join(options)}</ul>')
        )


# DeviceAdmin.get_inlines = device_admin_get_inlines
DeviceAdmin.conditional_inlines += [DeviceFirmwareInline, DeviceUpgradeOperationInline]

reversion.register(model=DeviceFirmware, follow=['device'])
reversion.register(model=UpgradeOperation)
DeviceAdmin.add_reversion_following(follow=['devicefirmware', 'upgradeoperation_set'])
