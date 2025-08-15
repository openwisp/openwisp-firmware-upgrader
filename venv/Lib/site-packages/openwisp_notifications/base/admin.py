from openwisp_notifications.base.forms import NotificationSettingForm


class NotificationSettingAdminMixin:
    fields = ['type', 'organization', 'web', 'email']
    readonly_fields = [
        'type',
        'organization',
    ]
    form = NotificationSettingForm

    def get_readonly_fields(self, request, obj=None):
        if request.user.is_superuser:
            return list()
        else:
            return self.readonly_fields

    def has_add_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .filter(deleted=False)
            .prefetch_related('organization')
        )

    class Media:
        extends = True
        js = [
            'admin/js/jquery.init.js',
            'openwisp-notifications/js/notification-settings.js',
        ]
