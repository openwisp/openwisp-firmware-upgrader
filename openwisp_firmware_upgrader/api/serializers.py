from rest_framework import serializers
from swapper import load_model


class BuildSerializer(serializers.ModelSerializer):
    class Meta:
        model = load_model('firmware_upgrader', 'Build')
        fields = '__all__'


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = load_model('firmware_upgrader', 'Category')
        fields = '__all__'


class UpgradeOperationSerializer(serializers.ModelSerializer):
    class Meta:
        model = load_model('firmware_upgrader', 'UpgradeOperation')
        fields = '__all__'


class BatchUpgradeOperationSerializer(serializers.ModelSerializer):

    build = BuildSerializer()
    progress_report = serializers.CharField(max_length=200)
    success_rate = serializers.IntegerField()
    failed_rate = serializers.IntegerField()
    aborted_rate = serializers.IntegerField()
    upgradeoperations = UpgradeOperationSerializer(
        source="upgradeoperation_set", many=True
    )

    class Meta:
        model = load_model('firmware_upgrader', 'BatchUpgradeOperation')
        fields = '__all__'


class FirmwareImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = load_model('firmware_upgrader', 'FirmwareImage')
        fields = '__all__'
