import logging
from contextlib import contextmanager

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.sites.models import Site
from django.core.cache import cache
from django.db import models
from django.db.models.constraints import UniqueConstraint
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.functional import cached_property
from django.utils.html import mark_safe
from django.utils.module_loading import import_string
from django.utils.translation import gettext_lazy as _
from markdown import markdown
from notifications.base.models import AbstractNotification as BaseNotification
from swapper import get_model_name

from openwisp_notifications import settings as app_settings
from openwisp_notifications.exceptions import NotificationRenderException
from openwisp_notifications.types import (
    NOTIFICATION_CHOICES,
    get_notification_configuration,
)
from openwisp_notifications.utils import _get_absolute_url, _get_object_link
from openwisp_utils.base import UUIDModel

logger = logging.getLogger(__name__)


@contextmanager
def notification_render_attributes(obj, **attrs):
    """
    This context manager sets temporary attributes on
    the notification object to allowing rendering of
    notification.

    It can only be used to set aliases of the existing attributes.
    By default, it will set the following aliases:
        - actor_link -> actor_url
        - action_link -> action_url
        - target_link -> target_url
    """
    defaults = {
        'actor_link': 'actor_url',
        'action_link': 'action_url',
        'target_link': 'target_url',
    }
    defaults.update(attrs)

    for target_attr, source_attr in defaults.items():
        setattr(obj, target_attr, getattr(obj, source_attr))

    yield obj

    for attr in defaults.keys():
        delattr(obj, attr)


class AbstractNotification(UUIDModel, BaseNotification):
    CACHE_KEY_PREFIX = 'ow-notifications-'
    type = models.CharField(max_length=30, null=True, choices=NOTIFICATION_CHOICES)
    _actor = BaseNotification.actor
    _action_object = BaseNotification.action_object
    _target = BaseNotification.target

    class Meta(BaseNotification.Meta):
        abstract = True

    def __init__(self, *args, **kwargs):
        related_objs = [
            (opt, kwargs.pop(opt, None)) for opt in ('target', 'action_object', 'actor')
        ]
        super().__init__(*args, **kwargs)
        for opt, obj in related_objs:
            if obj is not None:
                setattr(self, f'{opt}_object_id', obj.pk)
                setattr(
                    self,
                    f'{opt}_content_type',
                    ContentType.objects.get_for_model(obj),
                )

    def __str__(self):
        return self.timesince()

    @classmethod
    def _cache_key(cls, *args):
        args = map(str, args)
        key = '-'.join(args)
        return f'{cls.CACHE_KEY_PREFIX}{key}'

    @classmethod
    def count_cache_key(cls, user_pk):
        return cls._cache_key(f'unread-{user_pk}')

    @classmethod
    def invalidate_unread_cache(cls, user):
        """
        Invalidate unread cache for user.
        """
        cache.delete(cls.count_cache_key(user.pk))

    def _get_related_object_url(self, field):
        """
        Returns URLs for "actor", "action_object" and "target" fields.
        """
        if self.type:
            # Generate URL according to the notification configuration
            config = get_notification_configuration(self.type)
            url = config.get(f'{field}_link', None)
            if url:
                try:
                    url_callable = import_string(url)
                    return url_callable(self, field=field, absolute_url=True)
                except ImportError:
                    return url
        return _get_object_link(self, field=field, absolute_url=True)

    @property
    def actor_url(self):
        return self._get_related_object_url(field='actor')

    @property
    def action_url(self):
        return self._get_related_object_url(field='action_object')

    @property
    def target_url(self):
        return self._get_related_object_url(field='target')

    @cached_property
    def message(self):
        with notification_render_attributes(self):
            return self.get_message()

    @cached_property
    def rendered_description(self):
        if not self.description:
            return
        with notification_render_attributes(self):
            data = self.data or {}
            desc = self.description.format(notification=self, **data)
        return mark_safe(markdown(desc))

    @property
    def email_message(self):
        with notification_render_attributes(self, target_link='redirect_view_url'):
            return self.get_message()

    def get_message(self):
        if not self.type:
            return self.description
        try:
            config = get_notification_configuration(self.type)
            data = self.data or {}
            if 'message' in data:
                md_text = data['message'].format(notification=self, **data)
            elif 'message' in config:
                md_text = config['message'].format(notification=self, **data)
            else:
                md_text = render_to_string(
                    config['message_template'], context=dict(notification=self, **data)
                ).strip()
        except (AttributeError, KeyError, NotificationRenderException) as exception:
            self._invalid_notification(
                self.pk,
                exception,
                'Error encountered in rendering notification message',
            )
        return mark_safe(markdown(md_text))

    @cached_property
    def email_subject(self):
        if self.type:
            try:
                config = get_notification_configuration(self.type)
                data = self.data or {}
                return config['email_subject'].format(
                    site=Site.objects.get_current(), notification=self, **data
                )
            except (AttributeError, KeyError, NotificationRenderException) as exception:
                self._invalid_notification(
                    self.pk,
                    exception,
                    'Error encountered in generating notification email',
                )
        elif self.data.get('email_subject', None):
            return self.data.get('email_subject')
        else:
            return self.message

    def _related_object(self, field):
        obj_id = getattr(self, f'{field}_object_id')
        obj_content_type_id = getattr(self, f'{field}_content_type_id')
        if not obj_id:
            return
        cache_key = self._cache_key(obj_content_type_id, obj_id)
        obj = cache.get(cache_key)
        if not obj:
            obj = getattr(self, f'_{field}')
            cache.set(
                cache_key,
                obj,
                timeout=app_settings.CACHE_TIMEOUT,
            )
        return obj

    def _invalid_notification(self, pk, exception, error_message):
        from openwisp_notifications.tasks import delete_notification

        logger.error(exception)
        delete_notification.delay(notification_id=pk)
        if isinstance(exception, NotificationRenderException):
            raise exception
        raise NotificationRenderException(error_message)

    @cached_property
    def actor(self):
        return self._related_object('actor')

    @cached_property
    def action_object(self):
        return self._related_object('action_object')

    @cached_property
    def target(self):
        return self._related_object('target')

    @property
    def redirect_view_url(self):
        return _get_absolute_url(
            reverse('notifications:notification_read_redirect', args=(self.pk,))
        )


class AbstractNotificationSetting(UUIDModel):
    _RECEIVE_HELP = (
        'Note: Non-superadmin users receive '
        'notifications only for organizations '
        'of which they are member of.'
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    type = models.CharField(
        max_length=30,
        null=True,
        choices=NOTIFICATION_CHOICES,
        verbose_name='Notification Type',
    )
    organization = models.ForeignKey(
        get_model_name('openwisp_users', 'Organization'),
        on_delete=models.CASCADE,
    )
    web = models.BooleanField(
        _('web notifications'), null=True, blank=True, help_text=_(_RECEIVE_HELP)
    )
    email = models.BooleanField(
        _('email notifications'), null=True, blank=True, help_text=_(_RECEIVE_HELP)
    )
    deleted = models.BooleanField(_('Delete'), null=True, blank=True, default=False)

    class Meta:
        abstract = True
        constraints = [
            UniqueConstraint(
                fields=['organization', 'type', 'user'],
                name='unique_notification_setting',
            ),
        ]
        verbose_name = _('user notification settings')
        verbose_name_plural = verbose_name
        ordering = ['organization', 'type']
        indexes = [
            models.Index(fields=['type', 'organization']),
        ]

    def __str__(self):
        return '{type} - {organization}'.format(
            type=self.type_config['verbose_name'],
            organization=self.organization,
        )

    def save(self, *args, **kwargs):
        if not self.web_notification:
            self.email = self.web_notification
        return super().save(*args, **kwargs)

    def full_clean(self, *args, **kwargs):
        if self.email == self.type_config['email_notification']:
            self.email = None
        if self.web == self.type_config['web_notification']:
            self.web = None
        return super().full_clean(*args, **kwargs)

    @property
    def type_config(self):
        return get_notification_configuration(self.type)

    @property
    def email_notification(self):
        if self.email is not None:
            return self.email
        return self.type_config.get('email_notification')

    @property
    def web_notification(self):
        if self.web is not None:
            return self.web
        return self.type_config.get('web_notification')


class AbstractIgnoreObjectNotification(UUIDModel):
    """
    This model stores information about ignoring notification
    from a specific object for a user. Any instance of the model
    should be only stored until "valid_till" expires.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    object_content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.CharField(max_length=255)
    object = GenericForeignKey('object_content_type', 'object_id')
    valid_till = models.DateTimeField(null=True)

    class Meta:
        abstract = True
        ordering = ['valid_till']
