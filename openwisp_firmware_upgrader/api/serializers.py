from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from openwisp_users.api.mixins import FilterSerializerByOrgManaged
from openwisp_utils.api.serializers import ValidatedModelSerializer

from ..constants import DISABLED_ORGANIZATION_FIRMWARE_ERROR
from ..fields import NaiveSplitDateTimeField
from ..swapper import load_model
from ..utils import reinterpret_in_timezone

BatchUpgradeOperation = load_model("BatchUpgradeOperation")
Build = load_model("Build")
Category = load_model("Category")
FirmwareImage = load_model("FirmwareImage")
UpgradeOperation = load_model("UpgradeOperation")
DeviceFirmware = load_model("DeviceFirmware")


class BaseMeta:
    read_only_fields = ["created", "modified"]


class BaseSerializer(FilterSerializerByOrgManaged, ValidatedModelSerializer):
    pass


class CategorySerializer(BaseSerializer):
    def validate_organization(self, value):
        if not value and not self.context.get("request").user.is_superuser:
            raise serializers.ValidationError(
                _("Only superusers can create or edit shared categories")
            )
        return value

    class Meta(BaseMeta):
        model = Category
        fields = "__all__"


class CategoryRelationSerializer(BaseSerializer):
    class Meta:
        model = Category
        fields = ["name", "organization"]


class FirmwareImageSerializer(BaseSerializer):
    def validate(self, data):
        data["build"] = (
            self.context["view"]
            .get_parent_queryset()
            .select_related("category__organization")
            .get()
        )
        # The URL supplies this read-only relation, bypassing field filtering.
        organization = data["build"].category.organization
        if organization is not None and not organization.is_active:
            raise PermissionDenied(DISABLED_ORGANIZATION_FIRMWARE_ERROR)
        return super().validate(data)

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        request = self.context.get("request")
        if request and getattr(instance, "pk", None):
            ret["file"] = request.build_absolute_uri(
                reverse(
                    "upgrader:api_firmware_download",
                    args=[instance.build.pk, instance.pk],
                )
            )
        elif hasattr(instance, "file"):
            ret["file"] = reverse(
                "upgrader:api_firmware_download",
                args=[instance.build.pk, instance.pk],
            )
        return ret

    class Meta(BaseMeta):
        model = FirmwareImage
        fields = "__all__"
        read_only_fields = BaseMeta.read_only_fields + ["build"]


class BuildSerializer(BaseSerializer):
    category_relation = CategoryRelationSerializer(read_only=True, source="category")

    class Meta(BaseMeta):
        model = Build
        fields = "__all__"


class TimezoneAwareDateTimeField(serializers.DateTimeField):
    def enforce_timezone(self, value):
        if timezone.is_naive(value):
            raise serializers.ValidationError(
                _(
                    "The scheduled time must include a timezone offset, "
                    "e.g. '2026-08-25T09:00:00Z'."
                )
            )
        return super().enforce_timezone(value)


class BatchUpgradeSerializer(FilterSerializerByOrgManaged, serializers.ModelSerializer):
    upgrade_all = serializers.BooleanField(required=False, default=False)
    is_persistent = serializers.BooleanField(required=False, default=True)
    scheduled_at = TimezoneAwareDateTimeField(required=False, allow_null=True)

    class Meta:
        fields = (
            "upgrade_all",
            "is_persistent",
            "group",
            "location",
            "scheduled_at",
        )
        model = BatchUpgradeOperation
        extra_kwargs = {
            "group": {"required": False, "allow_null": True},
            "location": {"required": False, "allow_null": True},
        }


class BatchUpgradeRescheduleSerializer(BatchUpgradeSerializer):
    upgrade_all = serializers.BooleanField(source="firmwareless", required=False)

    def to_internal_value(self, data):
        tz_name = data.get("scheduled_at_tz")
        if tz_name is not None:
            # Normalize split browser input before scheduled_at's ISO validation.
            # Keep the caller's data intact, including QueryDict submissions.
            normalized = data.copy()
            field = NaiveSplitDateTimeField(required=False)
            try:
                parsed = field.clean(
                    [data.get("scheduled_at_0"), data.get("scheduled_at_1")]
                )
                normalized["scheduled_at"] = (
                    reinterpret_in_timezone(parsed, tz_name) if parsed else None
                )
            except ValidationError as error:
                raise serializers.ValidationError({"error": error.messages[0]})
            data = normalized
        return super().to_internal_value(data)

    class Meta(BatchUpgradeSerializer.Meta):
        fields = BatchUpgradeSerializer.Meta.fields + ("build", "upgrade_options")
        read_only_fields = ("build", "upgrade_options")


class UpgradeOperationSerializer(serializers.ModelSerializer):
    class Meta:
        model = UpgradeOperation
        fields = (
            "id",
            "device",
            "image",
            "is_persistent",
            "retry_count",
            "next_retry_at",
            "status",
            "log",
            "progress",
            "modified",
            "created",
        )
        read_only_fields = ("is_persistent", "retry_count", "next_retry_at")


class DeviceUpgradeOperationSerializer(serializers.ModelSerializer):
    class Meta:
        model = UpgradeOperation
        fields = (
            "id",
            "device",
            "image",
            "is_persistent",
            "retry_count",
            "next_retry_at",
            "status",
            "log",
            "progress",
            "modified",
        )
        read_only_fields = ("is_persistent", "retry_count", "next_retry_at")


class BatchUpgradeOperationListSerializer(BaseSerializer):
    build = BuildSerializer(read_only=True)
    initiated_by = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = BatchUpgradeOperation
        fields = "__all__"


class BatchUpgradeOperationSerializer(BatchUpgradeOperationListSerializer):
    progress_report = serializers.CharField(max_length=200)
    success_rate = serializers.IntegerField(read_only=True)
    failed_rate = serializers.IntegerField(read_only=True)
    aborted_rate = serializers.IntegerField(read_only=True)
    cancelled_rate = serializers.IntegerField(read_only=True)
    upgradeoperations = UpgradeOperationSerializer(
        read_only=True, source="upgradeoperation_set", many=True
    )

    class Meta:
        model = BatchUpgradeOperation
        fields = "__all__"


class DeviceFirmwareSerializer(ValidatedModelSerializer):
    is_persistent = serializers.BooleanField(
        required=False, default=False, write_only=True
    )

    class Meta:
        model = DeviceFirmware
        fields = ("id", "image", "installed", "is_persistent", "modified")
        read_only_fields = ("installed", "modified")

    def create(self, validated_data):
        is_persistent = validated_data.pop("is_persistent", False)
        instance = DeviceFirmware(**validated_data)
        instance.save(is_persistent=is_persistent)
        return instance

    def update(self, instance, validated_data):
        is_persistent = validated_data.pop("is_persistent", False)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save(is_persistent=is_persistent)
        return instance

    def validate(self, data):
        if not data.get("device"):
            data.update({"device": self.context.get("device")})
        return super().validate(data)
