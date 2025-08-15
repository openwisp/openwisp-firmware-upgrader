import logging

from django.db import models
from rest_framework import serializers
from rest_framework.exceptions import NotFound

from openwisp_notifications.exceptions import NotificationRenderException
from openwisp_notifications.swapper import load_model

logger = logging.getLogger(__name__)

Notification = load_model('Notification')
NotificationSetting = load_model('NotificationSetting')
IgnoreObjectNotification = load_model('IgnoreObjectNotification')


class ContentTypeField(serializers.Field):
    def to_representation(self, obj):
        return obj.model


class CustomListSerializer(serializers.ListSerializer):
    def to_representation(self, data):
        iterable = data.all() if isinstance(data, models.Manager) else data
        data_list = []
        for item in iterable:
            try:
                data_list.append(self.child.to_representation(item))
            except NotificationRenderException as e:
                logger.error(e)
        return data_list


class NotificationSerializer(serializers.ModelSerializer):
    actor_content_type = ContentTypeField(read_only=True)
    target_content_type = ContentTypeField(read_only=True)
    action_object_content_type = ContentTypeField(read_only=True)

    class Meta:
        model = Notification
        exclude = ['description', 'deleted', 'public']
        extra_fields = ['message', 'email_subject', 'target_url']

    def get_field_names(self, declared_fields, info):
        model_fields = super().get_field_names(declared_fields, info)
        return model_fields + self.Meta.extra_fields

    @property
    def data(self):
        try:
            return super().data
        except NotificationRenderException as e:
            logger.error(e)
            raise NotFound


class NotificationListSerializer(NotificationSerializer):
    description = serializers.CharField(source='rendered_description')

    class Meta(NotificationSerializer.Meta):
        fields = [
            'id',
            'message',
            'description',
            'unread',
            'target_url',
            'email_subject',
            'timestamp',
            'level',
        ]
        exclude = None
        list_serializer_class = CustomListSerializer


class NotificationSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationSetting
        exclude = ['user']
        read_only_fields = ['organization', 'type']


class IgnoreObjectNotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = IgnoreObjectNotification
        exclude = ['user']
        read_only_fields = [
            'object_content_type',
            'object_id',
        ]
