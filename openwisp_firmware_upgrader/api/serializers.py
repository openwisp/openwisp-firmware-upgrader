from django import forms
from django.core.exceptions import ValidationError as DjangoValidationError
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from openwisp_users.api.mixins import FilterSerializerByOrgManaged
from openwisp_utils.api.serializers import ValidatedModelSerializer

from ..swapper import load_model

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
        data["build"] = self.context["view"].get_parent_queryset().get()
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


class BatchUpgradeSerializer(FilterSerializerByOrgManaged, serializers.ModelSerializer):
    upgrade_all = serializers.BooleanField(required=False, default=False)
    is_persistent = serializers.BooleanField(required=False, default=True)

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
    class Meta(BatchUpgradeSerializer.Meta):
        fields = BatchUpgradeSerializer.Meta.fields + ("build", "upgrade_options")
        read_only_fields = ("build", "upgrade_options")

    def to_internal_value(self, data):
        # The admin panel posts the two AdminSplitDateTime inputs; combine them
        # via the create form's field so the wall-clock is read in the server
        # timezone. A direct scheduled_at (API clients) is left untouched.
        if "scheduled_at_0" in data or "scheduled_at_1" in data:
            data = data.copy() if hasattr(data, "copy") else dict(data)
            date_value = data.get("scheduled_at_0") or ""
            time_value = data.get("scheduled_at_1") or ""
            data.pop("scheduled_at_0", None)
            data.pop("scheduled_at_1", None)
            if date_value or time_value:
                try:
                    data["scheduled_at"] = forms.SplitDateTimeField(
                        required=False
                    ).clean([date_value, time_value])
                except DjangoValidationError as error:
                    raise serializers.ValidationError({"scheduled_at": error.messages})
            else:
                data["scheduled_at"] = None
        return super().to_internal_value(data)


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
