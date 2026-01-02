import swapper
from django.core.exceptions import ValidationError
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
Device = swapper.load_model("config", "Device")


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


class UpgradeOperationSerializer(serializers.ModelSerializer):
    class Meta:
        model = UpgradeOperation
        fields = (
            "id",
            "device",
            "image",
            "status",
            "log",
            "modified",
            "created",
            "upgrade_options",
        )


class DeviceUpgradeOperationSerializer(serializers.ModelSerializer):
    class Meta:
        model = UpgradeOperation
        fields = (
            "id",
            "device",
            "image",
            "status",
            "log",
            "modified",
            "upgrade_options",
        )


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
    upgradeoperations = UpgradeOperationSerializer(
        read_only=True, source="upgradeoperation_set", many=True
    )

    class Meta:
        model = BatchUpgradeOperation
        fields = "__all__"


class DeviceFirmwareSerializer(ValidatedModelSerializer):
    upgrade_options = serializers.JSONField(required=False, allow_null=True)

    class Meta:
        model = DeviceFirmware
        fields = ("id", "image", "installed", "modified", "upgrade_options")
        read_only_fields = ("installed", "modified")

    def validate(self, data):
        if not data.get("device"):
            device_id = self.context.get("device_id")
            device = self._get_device_object(device_id)
            data.update({"device": device})
        image = data.get("image")
        device = data.get("device")
        if (
            image
            and device
            and image.build.category.organization is not None
            and image.build.category.organization != device.organization
        ):
            raise ValidationError(
                {
                    "image": _(
                        "The organization of the image doesn't "
                        "match the organization of the device"
                    )
                }
            )
        # Validate upgrade_options if provided
        upgrade_options = data.get("upgrade_options")
        if upgrade_options is not None:
            # Create a temporary UpgradeOperation to validate upgrade_options
            # This will trigger the model's validation logic
            temp_operation = UpgradeOperation(
                device=device,
                image=image,
                upgrade_options=upgrade_options or {},
            )
            try:
                temp_operation.validate_upgrade_options()
            except ValidationError as e:
                raise serializers.ValidationError({"upgrade_options": e.messages})
        return super().validate(data)

    def to_representation(self, instance):
        """
        Include upgrade_options from the latest upgrade operation if available.
        """
        ret = super().to_representation(instance)
        # Get upgrade_options from the latest upgrade operation for this device
        try:
            latest_operation = instance.device.upgradeoperation_set.latest("created")
            ret["upgrade_options"] = latest_operation.upgrade_options
        except UpgradeOperation.DoesNotExist:
            ret["upgrade_options"] = {}
        return ret

    def create(self, validated_data):
        """
        Extract upgrade_options from validated_data and pass it to model.save()
        """
        upgrade_options = validated_data.pop("upgrade_options", None)
        if upgrade_options is None:
            upgrade_options = {}
        instance = DeviceFirmware(**validated_data)
        instance.save(upgrade_options=upgrade_options)
        return instance

    def update(self, instance, validated_data):
        """
        Extract upgrade_options from validated_data and pass it to model.save()
        """
        upgrade_options = validated_data.pop("upgrade_options", None)
        if upgrade_options is None:
            upgrade_options = {}
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save(upgrade_options=upgrade_options)
        return instance

    def _get_device_object(self, device_id):
        try:
            device = Device.objects.get(id=device_id)
            return device
        except Device.DoesNotExist:
            return None
