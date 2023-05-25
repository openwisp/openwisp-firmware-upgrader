import swapper
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from openwisp_users.api.mixins import FilterSerializerByOrgManaged
from openwisp_utils.api.serializers import ValidatedModelSerializer

from ..swapper import load_model

BatchUpgradeOperation = load_model('BatchUpgradeOperation')
Build = load_model('Build')
Category = load_model('Category')
FirmwareImage = load_model('FirmwareImage')
UpgradeOperation = load_model('UpgradeOperation')
DeviceFirmware = load_model('DeviceFirmware')
Device = swapper.load_model('config', 'Device')


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


class UpgradeOperationSerializer(serializers.ModelSerializer):
    class Meta:
        model = UpgradeOperation
        fields = ('id', 'device', 'image', 'status', 'log', 'modified', 'created')


class DeviceUpgradeOperationSerializer(serializers.ModelSerializer):
    class Meta:
        model = UpgradeOperation
        fields = ('id', 'device', 'image', 'status', 'log', 'modified')


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


class DeviceFirmwareSerializer(ValidatedModelSerializer):
    class Meta:
        model = DeviceFirmware
        fields = ('id', 'image', 'installed', 'modified')
        read_only_fields = ('installed', 'modified')

    def validate(self, data):
        if not data.get('device'):
            device_id = self.context.get('device_id')
            device = self._get_device_object(device_id)
            data.update({'device': device})
        image = data.get('image')
        device = data.get('device')
        if (
            image
            and device
            and image.build.category.organization != device.organization
        ):
            raise ValidationError(
                {
                    'image': _(
                        'The organization of the image doesn\'t '
                        'match the organization of the device'
                    )
                }
            )
        return super().validate(data)

    def _get_device_object(self, device_id):
        try:
            device = Device.objects.get(id=device_id)
            return device
        except Device.DoesNotExist:
            return None
