from django.forms import ModelForm, widgets

from openwisp_notifications.swapper import swapper_load_model


class NotificationSettingForm(ModelForm):
    def __init__(self, *args, **kwargs):
        instance = kwargs.get('instance')
        if instance:
            kwargs['initial'] = {
                'web': instance.web_notification,
                'email': (
                    instance.email_notification
                    if instance.web_notification
                    else instance.web_notification
                ),
            }
        super().__init__(*args, **kwargs)
        try:
            self.fields['organization'].choices = self.get_organization_choices()
        except KeyError:
            pass

    @classmethod
    def get_organization_choices(cls):
        if not hasattr(cls, 'organization_choices'):
            Organization = swapper_load_model('openwisp_users', 'organization')
            cls.organization_choices = [(None, '---------')] + list(
                Organization.objects.all().values_list('pk', 'name')
            )
        return cls.organization_choices

    class Meta:
        widgets = {
            'web': widgets.CheckboxInput,
            'email': widgets.CheckboxInput,
        }
