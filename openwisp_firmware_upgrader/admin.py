import json
import logging
from datetime import timedelta

import reversion
import swapper
from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.core.exceptions import ValidationError
from django.core.paginator import InvalidPage, Paginator
from django.core.serializers.json import DjangoJSONEncoder
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.templatetags.static import static
from django.urls import resolve, reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.timezone import localtime
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _
from reversion.admin import VersionAdmin

from openwisp_controller.config.admin import DeactivatedDeviceReadOnlyMixin, DeviceAdmin
from openwisp_users.multitenancy import MultitenantAdminMixin, MultitenantOrgFilter
from openwisp_utils.admin import ReadOnlyAdmin, TimeReadonlyAdminMixin

from .filters import (
    BuildCategoryFilter,
    BuildCategoryOrganizationFilter,
    BuildFilter,
    CategoryFilter,
    CategoryOrganizationFilter,
    GroupFilter,
    LocationFilter,
)
from .swapper import load_model
from .utils import get_upgrader_schema_for_device
from .widgets import FirmwareSchemaWidget, MassUpgradeSelect2Widget

logger = logging.getLogger(__name__)
BatchUpgradeOperation = load_model("BatchUpgradeOperation")
UpgradeOperation = load_model("UpgradeOperation")
DeviceFirmware = load_model("DeviceFirmware")
FirmwareImage = load_model("FirmwareImage")
Category = load_model("Category")
Build = load_model("Build")
Device = swapper.load_model("config", "Device")
DeviceConnection = swapper.load_model("connection", "DeviceConnection")
Organization = swapper.load_model("openwisp_users", "Organization")
Location = swapper.load_model("geo", "Location")
DeviceGroup = swapper.load_model("config", "DeviceGroup")


class BaseAdmin(MultitenantAdminMixin, TimeReadonlyAdminMixin, admin.ModelAdmin):
    save_on_top = True


class BaseVersionAdmin(MultitenantAdminMixin, TimeReadonlyAdminMixin, VersionAdmin):
    history_latest_first = True
    save_on_top = True


@admin.register(load_model("Category"))
class CategoryAdmin(BaseVersionAdmin):
    list_display = ["name", "organization", "created", "modified"]
    list_filter = [MultitenantOrgFilter]
    list_select_related = ["organization"]
    search_fields = ["name"]
    ordering = ["-name", "-created"]


class FirmwareImageInline(TimeReadonlyAdminMixin, admin.StackedInline):
    model = FirmwareImage
    extra = 0

    class Media:
        extra = "" if getattr(settings, "DEBUG", False) else ".min"
        i18n_name = admin.widgets.SELECT2_TRANSLATIONS.get(get_language())
        i18n_file = (
            ("admin/js/vendor/select2/i18n/%s.js" % i18n_name,) if i18n_name else ()
        )
        js = (
            (
                "admin/js/vendor/jquery/jquery%s.js" % extra,
                "admin/js/vendor/select2/select2.full%s.js" % extra,
            )
            + i18n_file
            + ("admin/js/jquery.init.js", "firmware-upgrader/js/build.js")
        )

        css = {
            "screen": ("admin/css/vendor/select2/select2%s.css" % extra,),
        }

    def has_change_permission(self, request, obj=None):
        if obj:
            return False
        return True


class BatchUpgradeConfirmationForm(forms.ModelForm):
    upgrade_options = forms.JSONField(widget=FirmwareSchemaWidget(), required=False)
    build = forms.ModelChoiceField(
        widget=forms.HiddenInput(), required=False, queryset=Build.objects.all()
    )
    group = forms.ModelChoiceField(
        queryset=DeviceGroup.objects.none(),
        required=False,
        help_text=_("Limit the upgrade to devices belonging to this group"),
        widget=MassUpgradeSelect2Widget(placeholder=_("Select a group")),
    )
    location = forms.ModelChoiceField(
        queryset=Location.objects.none(),
        required=False,
        help_text=_("Limit the upgrade to devices at this location"),
        widget=MassUpgradeSelect2Widget(placeholder=_("Select a location")),
    )

    class Meta:
        model = BatchUpgradeOperation
        fields = ("build", "group", "location", "upgrade_options")

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user")
        super().__init__(*args, **kwargs)
        build = self.initial.get("build")
        device_group_qs = DeviceGroup.objects
        location_qs = Location.objects
        organization_id = None
        if build:
            organization_id = build.category.organization_id
        if organization_id:
            device_group_qs = device_group_qs.filter(organization_id=organization_id)
            location_qs = location_qs.filter(organization_id=organization_id)
        if not self.user.is_superuser:
            device_group_qs = device_group_qs.filter(
                organization_id__in=self.user.organizations_managed
            )
            location_qs = location_qs.filter(
                organization_id__in=self.user.organizations_managed
            )
        self.fields["group"].queryset = device_group_qs
        self.fields["location"].queryset = location_qs

    class Media:
        # We don't need to include any select2 JS/CSS files as they are
        # included by the JSONSchemaWidget used for upgrade_options.
        js = [
            "admin/js/jquery.init.js",
            "firmware-upgrader/js/upgrade-selected-confirmation.js",
            "firmware-upgrader/js/mass-upgrade-select2.js",
        ]
        css = {
            "all": [
                "admin/css/forms.css",
                "admin/css/autocomplete.css",
                "admin/css/ow-auto-filter.css",
                "firmware-upgrader/css/upgrade-selected-confirmation.css",
            ]
        }


@admin.register(load_model("Build"))
class BuildAdmin(BaseAdmin):
    list_display = ["__str__", "organization", "category", "created", "modified"]
    list_filter = [CategoryOrganizationFilter, CategoryFilter]
    list_select_related = ["category", "category__organization"]
    search_fields = ["category__name", "version", "os"]
    ordering = ["-created", "-version"]
    inlines = [FirmwareImageInline]
    actions = ["upgrade_selected"]
    multitenant_parent = "category"
    autocomplete_fields = ["category"]

    # Allows apps that extend this modules to use this template with less hacks
    change_form_template = "admin/firmware_upgrader/change_form.html"

    def organization(self, obj):
        return obj.category.organization

    organization.short_description = _("organization")

    @admin.action(
        description=_("Mass-upgrade devices related to the selected build"),
        permissions=["change"],
    )
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
                    "Multiple mass upgrades requested but at the moment only "
                    "a single mass upgrade operation at time is supported."
                ),
                messages.ERROR,
            )
            # returning None will display the change list page again
            return None
        upgrade_all = request.POST.get("upgrade_all")
        upgrade_related = request.POST.get("upgrade_related")
        upgrade_options = request.POST.get("upgrade_options")
        group_id = request.POST.get("group")
        location_id = request.POST.get("location")
        build = queryset.first()
        form = BatchUpgradeConfirmationForm(initial={"build": build}, user=request.user)
        # upgrade has been confirmed
        if upgrade_all or upgrade_related:
            form = BatchUpgradeConfirmationForm(
                data={
                    "upgrade_options": upgrade_options,
                    "build": build,
                    "group": group_id,
                    "location": location_id,
                },
                user=request.user,
            )
            form.full_clean()
            if not form.errors:
                upgrade_options = form.cleaned_data["upgrade_options"]
                group = form.cleaned_data.get("group")
                location = form.cleaned_data.get("location")
                try:
                    batch = build.batch_upgrade(
                        firmwareless=upgrade_all,
                        upgrade_options=upgrade_options,
                        group=group,
                        location=location,
                    )
                    # Success message for when batch upgrade starts successfully
                    text = _(
                        "You can track the progress of this mass upgrade operation "
                        "in this page."
                    )
                    self.message_user(request, mark_safe(text), messages.SUCCESS)
                    url = reverse(
                        f"admin:{app_label}_batchupgradeoperation_change",
                        args=[batch.pk],
                    )
                    return redirect(url)
                except ValidationError as e:
                    self.message_user(
                        request, str(e.messages[0] if e.messages else e), messages.ERROR
                    )
        dry_run_kwargs = {
            "build": build,
        }
        if form.is_bound:
            group = form.cleaned_data.get("group") if not form.errors else None
            location = form.cleaned_data.get("location") if not form.errors else None
            dry_run_kwargs["group"] = group
            dry_run_kwargs["location"] = location
        result = BatchUpgradeOperation.dry_run(
            **dry_run_kwargs,
        )
        related_device_fw = result["device_firmwares"]
        firmwareless_devices = result["devices"]
        title = _("Confirm mass upgrade operation")
        context = self.admin_site.each_context(request)
        upgrader_schema = BatchUpgradeOperation(build=build)._get_upgrader_schema(
            related_device_fw=related_device_fw,
            firmwareless_devices=firmwareless_devices,
        )
        context.update(
            {
                "title": title,
                "related_device_fw": related_device_fw,
                "related_count": len(related_device_fw),
                "firmwareless_devices": firmwareless_devices,
                "firmwareless_count": len(firmwareless_devices),
                "form": form,
                "firmware_upgrader_schema": json.dumps(
                    upgrader_schema, cls=DjangoJSONEncoder
                ),
                "upgrade_operation_path": reverse(
                    f"admin:{app_label}_upgradeoperation_change",
                    args=["00000000-0000-0000-0000-000000000000"],
                ),
                "build": build,
                "opts": opts,
                "action_checkbox_name": ACTION_CHECKBOX_NAME,
                "media": self.media + form.media,
            }
        )
        request.current_app = self.admin_site.name
        return TemplateResponse(
            request,
            [
                "admin/%s/%s/upgrade_selected_confirmation.html"
                % (app_label, opts.model_name),
                "admin/%s/upgrade_selected_confirmation.html" % app_label,
                "admin/upgrade_selected_confirmation.html",
            ],
            context,
        )

    def change_view(self, request, object_id, extra_context=None, **kwargs):
        app_label = self.model._meta.app_label
        extra_context = extra_context or {}
        upgrade_url = f"{app_label}_build_changelist"
        extra_context.update({"upgrade_url": upgrade_url})
        extra_context["django_locale"] = get_language()
        return super().change_view(
            request, object_id, extra_context=extra_context, **kwargs
        )


class UpgradeOperationForm(forms.ModelForm):
    class Meta:
        fields = ["image", "status", "log", "modified"]
        labels = {"modified": _("last updated")}


class UpgradeOperationInline(admin.StackedInline):
    model = UpgradeOperation
    form = UpgradeOperationForm
    readonly_fields = UpgradeOperationForm.Meta.fields
    extra = 0

    def has_delete_permission(self, request, obj):
        return False

    def has_add_permission(self, request, obj):
        return False

    class Media:
        css = {"all": ["firmware-upgrader/css/upgrade-options.css"]}


class ReadonlyUpgradeOptionsMixin:

    class Media:
        css = {"all": ["firmware-upgrader/css/upgrade-options.css"]}

    @admin.display(description=_("Upgrade options"))
    def readonly_upgrade_options(self, obj):
        upgrader_schema = obj.upgrader_schema
        if not upgrader_schema:
            return _("Upgrade options are not supported for this upgrader.")
        options = []
        for key, value in upgrader_schema["properties"].items():
            option_used = "yes" if obj.upgrade_options.get(key, False) else "no"
            option_title = value["title"]
            icon_url = static(f"admin/img/icon-{option_used}.svg")
            options.append(
                format_html(
                    '<li><img src="{}" alt="{}">{}</li>',
                    icon_url,
                    _(option_used),
                    option_title,
                )
            )
        return format_html(
            '<ul class="readonly-upgrade-options">{}</ul>',
            mark_safe("".join(options)),
        )


@admin.register(UpgradeOperation)
class UpgradeOperationAdmin(ReadonlyUpgradeOptionsMixin, ReadOnlyAdmin, BaseAdmin):
    form = UpgradeOperationForm
    list_display = ["device", "status", "image", "modified"]
    list_filter = ["status"]
    search_fields = ["device__name"]
    readonly_fields = ["device", "image", "status", "log", "modified"]
    ordering = ["-modified"]
    fields = [
        "device",
        "image",
        "status",
        "log",
        "readonly_upgrade_options",
        "modified",
    ]
    change_form_template = "admin/firmware_upgrader/upgrade_operation_change_form.html"

    def _should_display_batch(self, obj, fields):
        return (
            obj
            and hasattr(obj, "batch")
            and obj.batch is not None
            and "batch" not in fields
        )

    def get_readonly_fields(self, request, obj=None):
        # Since "readonly_upgrade_options" is dynamically added, we need to
        # override get_readonly_fields to include it.
        fields = super().get_readonly_fields(request, obj).copy()
        if "readonly_upgrade_options" not in fields:
            fields.append("readonly_upgrade_options")
        if self._should_display_batch(obj, fields):
            fields.append("batch")
        return fields

    def change_view(self, request, object_id, extra_context=None, **kwargs):
        extra_context = extra_context or {}
        extra_context["upgrade_operation_cancel_url"] = reverse(
            "upgrader:api_upgradeoperation_cancel",
            args=["00000000-0000-0000-0000-000000000000"],
        )
        extra_context["django_locale"] = get_language()
        return super().change_view(
            request, object_id, extra_context=extra_context, **kwargs
        )

    def get_fields(self, request, obj=None):
        fields = super().get_fields(request, obj).copy()
        if self._should_display_batch(obj, fields):
            fields.insert(1, "batch")
        return fields

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(BatchUpgradeOperation)
class BatchUpgradeOperationAdmin(ReadonlyUpgradeOptionsMixin, ReadOnlyAdmin, BaseAdmin):
    list_display = ["build", "organization", "status", "created", "modified"]
    list_filter = [
        BuildCategoryOrganizationFilter,
        "status",
        BuildCategoryFilter,
        BuildFilter,
        GroupFilter,
        LocationFilter,
        "created",
    ]
    list_select_related = ["build__category__organization", "group", "location"]
    ordering = ["-created"]
    multitenant_parent = "build__category"
    fields = [
        "build",
        "group",
        "location",
        "status",
        "completed",
        "success_rate",
        "failed_rate",
        "aborted_rate",
        "cancelled_rate",
        "readonly_upgrade_options",
        "created",
        "modified",
    ]
    autocomplete_fields = ["build", "group", "location"]
    readonly_fields = [
        "completed",
        "success_rate",
        "failed_rate",
        "aborted_rate",
        "cancelled_rate",
        "readonly_upgrade_options",
    ]
    change_form_template = (
        "admin/firmware_upgrader/batch_upgrade_operation_change_form.html"
    )
    device_upgrades_per_page = 20

    def get_upgrade_operations(self, request, obj):
        qs = obj.upgradeoperation_set.select_related("device", "image")
        if request.user.is_superuser:
            return qs
        return qs.filter(device__organization_id__in=request.user.organizations_managed)

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["title"] = _("Mass upgrade operations")
        return super().changelist_view(request, extra_context)

    def _build_filter_specs(self, request, obj, current_status, current_org):
        """Return a list of filter spec objects for the change view.

        ``upgrades_qs`` is not strictly required here but could be passed if
        future filters need to inspect the queryset.  For now the filters are
        based on request parameters and the build's organization.
        """
        filter_specs = []
        # Status filter
        status_choices = []
        # build a base QueryDict with all current GET params
        params = request.GET.copy()

        # generic choice builder used by both status and organization filters
        def _make_choice(current_value, display, param_name, value):
            # start with a fresh copy so we don't mutate params
            q = params.copy()
            # always remove existing key for this filter
            q.pop(param_name, None)
            if value:
                q[param_name] = value
            qs = q.urlencode()
            query_string = f"?{qs}" if qs else ""
            return {
                "display": display,
                "selected": current_value == value,
                "query_string": query_string,
            }

        for status_value, display_name in (
            ("", _("All")),
        ) + UpgradeOperation.STATUS_CHOICES:
            status_choices.append(
                _make_choice(current_status, display_name, "status", status_value)
            )

        class StatusFilter:
            title = _("status")
            choices = status_choices

        filter_specs.append(StatusFilter())
        # Organization filter (only for shared builds)
        if obj.build.category.organization is None:
            org_choices = []
            # "All" choice is selected when there is no current_org value
            org_choices.append(_make_choice(current_org, _("All"), "organization", ""))
            org_qs = Organization.objects
            if not request.user.is_superuser:
                org_qs = org_qs.filter(id__in=request.user.organizations_managed)
            for org in org_qs.order_by("name"):
                org_choices.append(
                    _make_choice(current_org, org.name, "organization", str(org.id))
                )

            class OrganizationFilter:
                title = _("organization")
                choices = org_choices

            filter_specs.append(OrganizationFilter())
        return filter_specs

    def _paginate_operations(self, upgrades_qs, page_param, per_page=None):
        """Paginate ``upgrades_qs`` returning (page_obj, paginator, object_list)."""
        per_page = per_page or self.device_upgrades_per_page
        paginator = Paginator(upgrades_qs.order_by("id"), per_page)
        page_number = page_param or 1
        try:
            page_obj = paginator.page(page_number)
        except InvalidPage:
            page_obj = paginator.page(1)
        return page_obj, paginator, page_obj.object_list

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        obj = self.get_object(request, object_id)
        if obj:
            upgrades_qs = self.get_upgrade_operations(request, obj)
            search_query = request.GET.get("q", "")
            if search_query:
                upgrades_qs = upgrades_qs.filter(device__name__icontains=search_query)
            # Get current filter values
            current_status = request.GET.get("status", "")
            current_org = request.GET.get("organization", "")
            # apply filters to queryset
            if current_status:
                upgrades_qs = upgrades_qs.filter(status=current_status)
            if current_org:
                upgrades_qs = upgrades_qs.filter(device__organization_id=current_org)
            # build filter specs and paginate results
            filter_specs = self._build_filter_specs(
                request, obj, current_status, current_org
            )
            page_obj, paginator, upgrade_operations = self._paginate_operations(
                upgrades_qs, request.GET.get("page", 1)
            )
            upgrade_operation_app_label = UpgradeOperation._meta.app_label
            extra_context.update(
                {
                    "upgrade_operations": upgrade_operations,
                    "page_obj": page_obj,
                    "paginator": paginator,
                    "filter_specs": filter_specs,
                    "has_active_filters": any(
                        request.GET.get(param) for param in ["status", "organization"]
                    ),
                    "upgrade_operation_app_label": upgrade_operation_app_label,
                }
            )
        return super().change_view(request, object_id, extra_context=extra_context)

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        return fields + self.__class__.readonly_fields

    def organization(self, obj):
        return obj.build.category.organization

    organization.short_description = _("organization")

    def completed(self, obj):
        return obj.progress_report

    def success_rate(self, obj):
        return self.__get_rate(obj.success_rate)

    def failed_rate(self, obj):
        return self.__get_rate(obj.failed_rate)

    def aborted_rate(self, obj):
        return self.__get_rate(obj.aborted_rate)

    def cancelled_rate(self, obj):
        return self.__get_rate(obj.cancelled_rate)

    def __get_rate(self, value):
        if value:
            return f"{value}%"
        return _("N/A")

    completed.short_description = _("completed")
    success_rate.short_description = _("success rate")
    failed_rate.short_description = _("failure rate")
    aborted_rate.short_description = _("abortion rate")
    cancelled_rate.short_description = _("cancellation rate")


class DeviceFirmwareForm(forms.ModelForm):
    upgrade_options = forms.JSONField(widget=FirmwareSchemaWidget, required=False)

    class Meta:
        model = DeviceFirmware
        fields = "__all__"

    class Media:
        js = ["admin/js/jquery.init.js", "firmware-upgrader/js/device-firmware.js"]
        css = {"all": ["firmware-upgrader/css/device-firmware.css"]}

    def __init__(self, device, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["image"].queryset = DeviceFirmware.get_image_queryset_for_device(
            device, device_firmware=self.instance
        )

    def full_clean(self):
        super().full_clean()
        if not self.is_bound:
            return
        if self.errors:
            return
        cleaned_data = getattr(self, "cleaned_data", {})
        device = cleaned_data.get("device")
        image = cleaned_data.get("image")
        upgrade_options = cleaned_data.get("upgrade_options")
        if not image:
            self.add_error("image", _("This field is required."))
            return
        if not device:
            return
        upgrade_op = UpgradeOperation(
            device=device,
            image=image,
            upgrade_options=upgrade_options,
        )
        try:
            upgrade_op.full_clean()
        except ValidationError as error:
            self.add_error(None, error)

    def save(self, commit=True):
        """
        Adapted from ModelForm.save()
        Passes "upgrade_options to DeviceFirmware.save()
        """
        if commit:
            # If committing, save the instance and the m2m data immediately.
            self.instance.save(upgrade_options=self.cleaned_data["upgrade_options"])
        return self.instance


class DeviceFormSet(forms.BaseInlineFormSet):
    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs["device"] = self.instance
        return kwargs


class DeviceFirmwareInline(
    MultitenantAdminMixin, DeactivatedDeviceReadOnlyMixin, admin.StackedInline
):
    model = DeviceFirmware
    formset = DeviceFormSet
    form = DeviceFirmwareForm
    exclude = ["created"]
    select_related = ["device", "image"]
    readonly_fields = ["installed", "modified"]
    verbose_name = _("Firmware")
    verbose_name_plural = verbose_name
    extra = 0
    multitenant_shared_relations = ["device"]
    template = "admin/firmware_upgrader/device_firmware_inline.html"
    # hack for openwisp-monitoring integartion
    # TODO: remove when this issue solved:
    # https://github.com/theatlantic/django-nested-admin/issues/128#issuecomment-665833142
    sortable_options = {"disabled": True}

    class Media:
        js = [
            "connection/js/lib/reconnecting-websocket.min.js",
            "firmware-upgrader/js/upgrade-utils.js",
            "firmware-upgrader/js/upgrade-progress.js",
        ]
        css = {
            "all": [
                "firmware-upgrader/css/upgrade-progress.css",
            ]
        }

    def _get_conditional_queryset(self, request, obj, select_related=False):
        return bool(obj)

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj=obj, **kwargs)
        if obj:
            try:
                schema = get_upgrader_schema_for_device(obj)
                formset.extra_context = json.dumps(schema, cls=DjangoJSONEncoder)
            except DeviceConnection.DoesNotExist:
                # We cannot retrieve the schema for upgrade options because this
                # device does not have any related DeviceConnection object.
                pass
        return formset


class DeviceUpgradeOperationForm(UpgradeOperationForm):
    class Meta(UpgradeOperationForm.Meta):
        pass

    def __init__(self, device, *args, **kwargs):
        self.device = device
        super().__init__(*args, **kwargs)


class DeviceUpgradeOperationInline(ReadonlyUpgradeOptionsMixin, UpgradeOperationInline):
    verbose_name = _("Recent Firmware Upgrades")
    verbose_name_plural = verbose_name
    formset = DeviceFormSet
    form = DeviceUpgradeOperationForm
    # hack for openwisp-monitoring integration
    # TODO: remove when this issue solved:
    # https://github.com/theatlantic/django-nested-admin/issues/128#issuecomment-665833142
    sortable_options = {"disabled": True}
    fields = [
        "device",
        "image",
        "status",
        "log",
        "readonly_upgrade_options",
        "modified",
    ]
    readonly_fields = fields

    class Media:
        js = [
            "connection/js/lib/reconnecting-websocket.min.js",
            "firmware-upgrader/js/upgrade-utils.js",
            "firmware-upgrader/js/upgrade-progress.js",
        ]
        css = {
            "all": [
                "firmware-upgrader/css/upgrade-progress.css",
                "firmware-upgrader/css/upgrade-options.css",
            ]
        }

    def get_queryset(self, request, select_related=True):
        """
        Return recent upgrade operations for this device
        (created within the last 7 days)
        """
        qs = super().get_queryset(request)
        resolved = resolve(request.path_info)
        if "object_id" in resolved.kwargs:
            seven_days = localtime() - timedelta(days=7)
            qs = qs.filter(
                device_id=resolved.kwargs["object_id"], created__gte=seven_days
            ).order_by("-created")
        if select_related:
            qs = qs.select_related()
        return qs

    def _get_conditional_queryset(self, request, obj, select_related=False):
        if obj:
            return self.get_queryset(request, select_related=False).exists()
        return False


# DeviceAdmin.get_inlines = device_admin_get_inlines
DeviceAdmin.conditional_inlines += [DeviceFirmwareInline, DeviceUpgradeOperationInline]

reversion.register(model=DeviceFirmware, follow=["device"])
reversion.register(model=UpgradeOperation)
DeviceAdmin.add_reversion_following(follow=["devicefirmware", "upgradeoperation_set"])
