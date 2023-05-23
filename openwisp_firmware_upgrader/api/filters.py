import swapper
from django_filters import rest_framework as filters

from openwisp_users.api.mixins import FilterDjangoByOrgManaged

from ..swapper import load_model

UpgradeOperation = load_model('UpgradeOperation')
Organization = swapper.load_model('openwisp_users', 'Organization')


class UpgradeOperationFilter(FilterDjangoByOrgManaged):
    device = filters.CharFilter(
        field_name='device',
    )
    image = filters.CharFilter(
        field_name='image',
    )

    class Meta:
        model = UpgradeOperation
        fields = ['device', 'image', 'status']


class DeviceUpgradeOperationFilter(FilterDjangoByOrgManaged):
    class Meta:
        model = UpgradeOperation
        fields = ['status']
