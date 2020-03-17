from django import forms
from django.utils.translation import ugettext_lazy as _


class UpgradeOperationForm(forms.ModelForm):
    class Meta:
        fields = ['device', 'image', 'status', 'log', 'modified']
        labels = {'modified': _('last updated')}
