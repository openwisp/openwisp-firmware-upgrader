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
    CategoryFilter,
    CategoryOrganizationFilter,
)
from .swapper import load_model
from .utils import get_upgrader_schema_for_device
from .widgets import FirmwareSchemaWidget

logger = logging.getLogger(__name__)
BatchUpgradeOperation = load_model("BatchUpgradeOperation")
UpgradeOperation = load_model("UpgradeOperation")
DeviceFirmware = load_model("DeviceFirmware")
FirmwareImage = load_model("FirmwareImage")
Category = load_model("Category")
Build = load_model("Build")
Device = swapper.load_model("config", "Device")
DeviceConnection = swapper.load_model("connection", "DeviceConnection")


class BaseAdmin(MultitenantAdminMixin, TimeReadonlyAdminMixin, admin.ModelAdmin):
    save_on_top = True


class BaseVersionAdmin(MultitenantAdminMixin, TimeReadonlyAdminMixin, VersionAdmin):
    history_latest_first = True
    save_on_top = True


@admin.register(Category)
class CategoryAdmin(BaseVersionAdmin):
    list_display = ["name", "organization", "created", "modified"]
    list_filter = [MultitenantOrgFilter]
    list_select_related = ["organization"]
    search_fields = ["name"]
    ordering = ["-name", "-created"]


class FirmwareImageInline(TimeReadonlyAdminMixin, admin.StackedInline):
    model = FirmwareImage
    extra = 0


class BatchUpgradeConfirmationForm(forms.ModelForm):
    upgrade_options = forms.JSONField(widget=FirmwareSchemaWidget(), required=False)
    build = forms.ModelChoiceField(
        widget=forms.HiddenInput(), required=False, queryset=Build.objects.all()
    )

    class Meta:
        model = BatchUpgradeOperation
        fields = ("build", "upgrade_options")


@admin.register(Build)
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

    def organization(self, obj):
        return obj.category.organization

    @admin.action(description=_("Mass-upgrade devices related to the selected build"))
    def upgrade_selected(self, request, queryset):
        if queryset.count() > 1:
            self.message_user(request, _("Only one upgrade can be done at a time."), messages.ERROR)
            return None

        build = queryset.first()
        upgrade_all = request.POST.get("upgrade_all")
        upgrade_related = request.POST.get("upgrade_related")
        upgrade_options = request.POST.get("upgrade_options")
        form = BatchUpgradeConfirmationForm()

        if upgrade_all or upgrade_related:
            form = BatchUpgradeConfirmationForm(data={"upgrade_options": upgrade_options, "build": build})
            form.full_clean()
            if not form.errors:
                upgrade_options = form.cleaned_data["upgrade_options"]
                batch = build.batch_upgrade(firmwareless=upgrade_all, upgrade_options=upgrade_options)
                self.message_user(request, mark_safe(_("Upgrade initiated.")), messages.SUCCESS)
                url = reverse(f"admin:{build._meta.app_label}_batchupgradeoperation_change", args=[batch.pk])
                return redirect(url)

        result = BatchUpgradeOperation.dry_run(build=build)
        context = self.admin_site.each_context(request)
        context.update({
            "title": _("Confirm upgrade"),
            "form": form,
            "related_device_fw": result["device_firmwares"],
            "firmwareless_devices": result["devices"],
            "build": build,
            "opts": self.model._meta,
            "action_checkbox_name": ACTION_CHECKBOX_NAME,
        })
        return TemplateResponse(request, "admin/firmware_upgrader/upgrade_selected_confirmation.html", context)


@admin.register(UpgradeOperation)
class UpgradeOperationAdmin(BaseAdmin):
    list_display = ["device", "image", "status", "created", "modified"]
    actions = ["retry_failed_upgrades"]

    @admin.action(description=_("Retry selected failed or aborted upgrade operations"))
    def retry_failed_upgrades(self, request, queryset):
        retried = 0
        for op in queryset:
            if op.status not in ["failed", "aborted"]:
                continue
            try:
                dfw = DeviceFirmware.objects.get(device=op.device)
                dfw.retry_upgrade()
                retried += 1
            except DeviceFirmware.DoesNotExist:
                self.message_user(request, _(f"DeviceFirmware not found for device {op.device}"), messages.WARNING)
            except Exception as e:
                self.message_user(request, _(f"Retry failed for {op.device}: {e}"), messages.ERROR)
        if retried:
            self.message_user(request, _(f"Retried {retried} upgrade operation(s)."), messages.SUCCESS)


reversion.register(DeviceFirmware, follow=["device"])
reversion.register(UpgradeOperation)
DeviceAdmin.add_reversion_following(follow=["devicefirmware", "upgradeoperation_set"])
DeviceAdmin.conditional_inlines += [] 
