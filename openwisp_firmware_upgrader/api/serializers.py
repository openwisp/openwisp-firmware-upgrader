from django.core.exceptions import ObjectDoesNotExist
from rest_framework import serializers

from openwisp_users.api.mixins import FilterSerializerByOrgManaged
from openwisp_utils.api.serializers import ValidatedModelSerializer

from ..swapper import load_model

BatchUpgradeOperation = load_model('BatchUpgradeOperation')
Build = load_model('Build')
Category = load_model('Category')
FirmwareImage = load_model('FirmwareImage')
UpgradeOperation = load_model('UpgradeOperation')
DeviceFirmware = load_model("DeviceFirmware")


class BaseMeta:
    read_only_fields = ['created', 'modified']


class BaseSerializer(FilterSerializerByOrgManaged, ValidatedModelSerializer):
    pass


class CategorySerializer(BaseSerializer):
    class Meta(BaseMeta):
        model = Category
        fields = '__all__'


class CategoryRelationSerializer(BaseSerializer):
    class Meta:
        model = Category
        fields = ['name', 'organization']


class FirmwareImageSerializer(BaseSerializer):
    def validate(self, data):
        data['build'] = self.context['view'].get_parent_queryset().get()
        return super().validate(data)

    class Meta(BaseMeta):
        model = FirmwareImage
        fields = '__all__'
        read_only_fields = BaseMeta.read_only_fields + ['build']


class BuildSerializer(BaseSerializer):
    category_relation = CategoryRelationSerializer(read_only=True, source='category')

    class Meta(BaseMeta):
        model = Build
        fields = '__all__'


class UpgradeOperationSerializer(BaseSerializer):
    class Meta:
        model = UpgradeOperation
        exclude = ['batch']


class DeviceUpgradeOperationSerializer(BaseSerializer):
    class Meta:
        model = UpgradeOperation
        fields = ['id']


class BatchUpgradeOperationListSerializer(BaseSerializer):
    build = BuildSerializer(read_only=True)

    class Meta:
        model = BatchUpgradeOperation
        fields = '__all__'


class BatchUpgradeOperationSerializer(BatchUpgradeOperationListSerializer):
    progress_report = serializers.CharField(max_length=200)
    success_rate = serializers.IntegerField(read_only=True)
    failed_rate = serializers.IntegerField(read_only=True)
    aborted_rate = serializers.IntegerField(read_only=True)
    upgradeoperations = UpgradeOperationSerializer(
        read_only=True, source='upgradeoperation_set', many=True
    )

    class Meta:
        model = BatchUpgradeOperation
        fields = '__all__'


class DeviceFirmwareSerializer(serializers.ModelSerializer):

    image = FirmwareImageSerializer(read_only=True)

    class Meta:
        model = DeviceFirmware
        fields = ('image', 'installed')

    def _validate(self, data):
        return data

    def get_firmware_object(self, image_id):
        try:
            image = FirmwareImage.objects.get(id=image_id)
            return image
        except ObjectDoesNotExist:
            return None

    def create(self, validated_data):
        validated_data.update({'device_id': self.context.get('device_id')})
        validated_data['image'] = self.get_firmware_object(self.context.get('image'))
        queryset = DeviceFirmware.objects.filter(
            device__pk=self.context.get('device_id')
        )

        validated_data['installed'] = True
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data['image'] = self.get_firmware_object(self.context.get('image'))
        validated_data.update({'device_id': self.context.get('device_id')})
        validated_data['installed'] = True
        return super().update(instance, validated_data)
