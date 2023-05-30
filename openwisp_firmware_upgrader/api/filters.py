from django.utils.translation import gettext_lazy as _
from django_filters import rest_framework as filters

from openwisp_users.api.mixins import FilterDjangoByOrgManaged

from ..swapper import load_model

UpgradeOperation = load_model('UpgradeOperation')


class UpgradeOperationFilter(FilterDjangoByOrgManaged):
    device = filters.CharFilter(
        field_name='device',
    )
    image = filters.CharFilter(
        field_name='image',
    )

    def _set_valid_filterform_lables(self):
        self.filters['device__organization'].label = _('Organization')
        self.filters['device__organization__slug'].label = _('Organization slug')

    def __init__(self, *args, **kwargs):
        super(UpgradeOperationFilter, self).__init__(*args, **kwargs)
        self._set_valid_filterform_lables()

    class Meta:
        model = UpgradeOperation
        fields = [
            'device__organization',
            'device__organization__slug',
            'device',
            'image',
            'status',
        ]


class DeviceUpgradeOperationFilter(FilterDjangoByOrgManaged):
    class Meta:
        model = UpgradeOperation
        fields = ['status']
