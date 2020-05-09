from rest_framework import serializers
from swapper import load_model

from openwisp_utils.api.serializers import ValidatedModelSerializer


class BaseMeta:
    read_only_fields = ['created', 'modified']


class CategorySerializer(ValidatedModelSerializer):
    class Meta(BaseMeta):
        model = load_model('firmware_upgrader', 'Category')
        fields = '__all__'


class CategoryRelationSerializer(ValidatedModelSerializer):
    class Meta:
        model = load_model('firmware_upgrader', 'Category')
        fields = ['name', 'organization']


class FirmwareImageSerializer(ValidatedModelSerializer):
    class Meta(BaseMeta):
        model = load_model('firmware_upgrader', 'FirmwareImage')
        fields = '__all__'


class BuildSerializer(ValidatedModelSerializer):
    category_relation = CategoryRelationSerializer(read_only=True, source='category')

    class Meta(BaseMeta):
        model = load_model('firmware_upgrader', 'Build')
        fields = '__all__'


class UpgradeOperationSerializer(ValidatedModelSerializer):
    class Meta:
        model = load_model('firmware_upgrader', 'UpgradeOperation')
        exclude = ['batch']


class BatchUpgradeOperationListSerializer(ValidatedModelSerializer):
    build = BuildSerializer(read_only=True)

    class Meta:
        model = load_model('firmware_upgrader', 'BatchUpgradeOperation')
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
        model = load_model('firmware_upgrader', 'BatchUpgradeOperation')
        fields = '__all__'
