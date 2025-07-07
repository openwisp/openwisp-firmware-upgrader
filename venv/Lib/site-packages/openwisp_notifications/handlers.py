import logging

from celery.exceptions import OperationalError
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.db.models.query import QuerySet
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone
from django.utils.translation import gettext as _

from openwisp_notifications import settings as app_settings
from openwisp_notifications import tasks
from openwisp_notifications.exceptions import NotificationRenderException
from openwisp_notifications.swapper import load_model, swapper_load_model
from openwisp_notifications.types import (
    NOTIFICATION_ASSOCIATED_MODELS,
    get_notification_configuration,
)
from openwisp_notifications.websockets import handlers as ws_handlers
from openwisp_utils.admin_theme.email import send_email

logger = logging.getLogger(__name__)

EXTRA_DATA = app_settings.get_config()['USE_JSONFIELD']

User = get_user_model()

Notification = load_model('Notification')
NotificationSetting = load_model('NotificationSetting')
IgnoreObjectNotification = load_model('IgnoreObjectNotification')

Group = swapper_load_model('openwisp_users', 'Group')
OrganizationUser = swapper_load_model('openwisp_users', 'OrganizationUser')
Organization = swapper_load_model('openwisp_users', 'Organization')


def notify_handler(**kwargs):
    """
    Handler function to create Notification instance upon action signal call.
    """
    # Pull the options out of kwargs
    kwargs.pop('signal', None)
    actor = kwargs.pop('sender')
    public = bool(kwargs.pop('public', True))
    description = kwargs.pop('description', None)
    timestamp = kwargs.pop('timestamp', timezone.now())
    recipient = kwargs.pop('recipient', None)
    notification_type = kwargs.pop('type', None)
    target = kwargs.get('target', None)
    target_org = getattr(target, 'organization_id', None)
    try:
        notification_template = get_notification_configuration(notification_type)
    except NotificationRenderException as error:
        logger.error(f'Error encountered while creating notification: {error}')
        return
    level = kwargs.pop(
        'level', notification_template.get('level', Notification.LEVELS.info)
    )
    verb = notification_template.get('verb', kwargs.pop('verb', None))
    user_app_name = User._meta.app_label

    where = Q(is_superuser=True)
    not_where = Q()
    where_group = Q()
    if target_org:
        org_admin_query = Q(
            **{
                f'{user_app_name}_organizationuser__organization': target_org,
                f'{user_app_name}_organizationuser__is_admin': True,
            }
        )
        where = where | (Q(is_staff=True) & org_admin_query)
        where_group = org_admin_query

        # We can only find notification setting if notification type and
        # target organization is present.
        if notification_type:
            # Create notification for users who have opted for receiving notifications.
            # For users who have not configured web_notifications,
            # use default from notification type
            web_notification = Q(notificationsetting__web=True)
            if notification_template['web_notification']:
                web_notification |= Q(notificationsetting__web=None)

            notification_setting = web_notification & Q(
                notificationsetting__type=notification_type,
                notificationsetting__organization_id=target_org,
                notificationsetting__deleted=False,
            )
            where = where & notification_setting
            where_group = where_group & notification_setting

    # Ensure notifications are only sent to active user
    where = where & Q(is_active=True)
    where_group = where_group & Q(is_active=True)

    # We can only find ignore notification setting if target object is present
    if target:
        not_where = Q(
            ignoreobjectnotification__object_id=target.pk,
            ignoreobjectnotification__object_content_type=ContentType.objects.get_for_model(
                target._meta.model
            ),
        ) & (
            Q(ignoreobjectnotification__valid_till=None)
            | Q(ignoreobjectnotification__valid_till__gt=timezone.now())
        )

    if recipient:
        # Check if recipient is User, Group or QuerySet
        if isinstance(recipient, Group):
            recipients = recipient.user_set.filter(where_group)
        elif isinstance(recipient, QuerySet):
            recipients = recipient.distinct()
        elif isinstance(recipient, list):
            recipients = recipient
        else:
            recipients = [recipient]
    else:
        recipients = (
            User.objects.prefetch_related(
                'notificationsetting_set', 'ignoreobjectnotification_set'
            )
            .order_by('date_joined')
            .filter(where)
            .exclude(not_where)
            .distinct()
        )
    optional_objs = [
        (kwargs.pop(opt, None), opt) for opt in ('target', 'action_object')
    ]

    notification_list = []
    for recipient in recipients:
        notification = Notification(
            recipient=recipient,
            actor=actor,
            verb=str(verb),
            public=public,
            description=description,
            timestamp=timestamp,
            level=level,
            type=notification_type,
        )

        # Set optional objects
        for obj, opt in optional_objs:
            if obj is not None:
                setattr(notification, '%s_object_id' % opt, obj.pk)
                setattr(
                    notification,
                    '%s_content_type' % opt,
                    ContentType.objects.get_for_model(obj),
                )
        if kwargs and EXTRA_DATA:
            notification.data = kwargs
        notification.save()
        notification_list.append(notification)

    return notification_list


@receiver(post_save, sender=Notification, dispatch_uid='send_email_notification')
def send_email_notification(sender, instance, created, **kwargs):
    # Abort if a new notification is not created
    if not created:
        return
    # Get email preference of user for this type of notification.
    target_org = getattr(getattr(instance, 'target', None), 'organization_id', None)
    if instance.type and target_org:
        try:
            notification_setting = instance.recipient.notificationsetting_set.get(
                organization=target_org, type=instance.type
            )
        except NotificationSetting.DoesNotExist:
            return
        email_preference = notification_setting.email_notification
    else:
        # We can not check email preference if notification type is absent,
        # or if target_org is not present
        # therefore send email anyway.
        email_preference = True

    email_verified = instance.recipient.emailaddress_set.filter(
        verified=True, email=instance.recipient.email
    ).exists()

    if not (email_preference and instance.recipient.email and email_verified):
        return

    try:
        subject = instance.email_subject
    except NotificationRenderException:
        # Do not send email if notification is malformed.
        return
    url = instance.data.get('url', '') if instance.data else None
    body_text = instance.email_message
    if url:
        target_url = url
    elif instance.target:
        target_url = instance.redirect_view_url
    else:
        target_url = None
    if target_url:
        body_text += _('\n\nFor more information see %(target_url)s.') % {
            'target_url': target_url
        }

    send_email(
        subject=subject,
        body_text=body_text,
        body_html=instance.email_message,
        recipients=[instance.recipient.email],
        extra_context={
            'call_to_action_url': target_url,
            'call_to_action_text': _('Find out more'),
        },
    )

    # flag as emailed
    instance.emailed = True
    # bulk_update is used to prevent emitting post_save signal
    Notification.objects.bulk_update([instance], ['emailed'])


@receiver(post_save, sender=Notification, dispatch_uid='clear_notification_cache_saved')
@receiver(
    post_delete, sender=Notification, dispatch_uid='clear_notification_cache_deleted'
)
def clear_notification_cache(sender, instance, **kwargs):
    Notification.invalidate_unread_cache(instance.recipient)
    # Reload notification widget only if notification is created or deleted
    # Display notification toast when a new notification is created
    ws_handlers.notification_update_handler(
        recipient=instance.recipient,
        reload_widget=kwargs.get('created', True),
        notification=instance if kwargs.get('created', None) else None,
    )


@receiver(post_delete, dispatch_uid='delete_obsolete_objects')
def related_object_deleted(sender, instance, **kwargs):
    """
    Delete Notification and IgnoreObjectNotification objects having
    "instance" as related object.
    """
    if sender not in NOTIFICATION_ASSOCIATED_MODELS:
        return
    instance_id = getattr(instance, 'pk', None)
    if instance_id:
        instance_model = instance._meta.model_name
        instance_app_label = instance._meta.app_label
        tasks.delete_obsolete_objects.delay(
            instance_app_label, instance_model, instance_id
        )


def notification_type_registered_unregistered_handler(sender, **kwargs):
    try:
        tasks.ns_register_unregister_notification_type.delay()
    except OperationalError:
        logger.warn(
            '\tCelery broker is unreachable, skipping populating data for user(s) '
            'notification preference(s).\n'
            '\tMake sure that celery broker is running and reachable by celery workers.\n'
            '\tYou can use following command later '
            'to populate data for user(s) notification preference(s).\n\n'
            '\t\t python manage.py populate_notification_preferences\n'
        )


@receiver(
    post_save,
    sender=OrganizationUser,
    dispatch_uid='create_orguser_notification_setting',
)
def organization_user_post_save(instance, created, **kwargs):
    transaction.on_commit(
        lambda: tasks.update_org_user_notificationsetting.delay(
            org_user_id=instance.pk,
            user_id=instance.user_id,
            org_id=instance.organization_id,
            is_org_admin=instance.is_admin,
        )
    )


@receiver(
    post_delete,
    sender=OrganizationUser,
    dispatch_uid='delete_orguser_notification_setting',
)
def notification_setting_delete_org_user(instance, **kwargs):
    tasks.ns_organization_user_deleted.delay(
        user_id=instance.user_id, org_id=instance.organization_id
    )


@receiver(pre_save, sender=User, dispatch_uid='superuser_demoted_notification_setting')
def update_superuser_notification_settings(instance, update_fields, **kwargs):
    """
    If user is demoted from superuser status, then
    remove notification settings for non-managed organizations.

    If user is promoted to superuser, then
    create notification settings for all organizations.
    """
    if update_fields is not None and 'is_superuser' not in update_fields:
        # No-op if is_superuser field is not being updated.
        # If update_fields is None, it means any field could be updated.
        return
    try:
        db_instance = User.objects.only('is_superuser').get(pk=instance.pk)
    except User.DoesNotExist:
        # User is being created
        return
    # If user is demoted from superuser to non-superuser
    if db_instance.is_superuser and not instance.is_superuser:
        transaction.on_commit(
            lambda: tasks.update_superuser_notification_settings.delay(
                instance.pk, is_superuser=False
            )
        )
    elif not db_instance.is_superuser and instance.is_superuser:
        transaction.on_commit(
            lambda: tasks.update_superuser_notification_settings.delay(
                instance.pk, is_superuser=True
            )
        )


@receiver(post_save, sender=User, dispatch_uid='create_superuser_notification_settings')
def create_superuser_notification_settings(instance, created, **kwargs):
    if created and instance.is_superuser:
        transaction.on_commit(
            lambda: tasks.create_superuser_notification_settings.delay(instance.pk)
        )


@receiver(
    post_save, sender=Organization, dispatch_uid='org_created_notification_setting'
)
def notification_setting_org_created(created, instance, **kwargs):
    if created:
        transaction.on_commit(lambda: tasks.ns_organization_created.delay(instance.pk))


@receiver(
    post_save,
    sender=IgnoreObjectNotification,
    dispatch_uid='schedule_object_notification_deletion',
)
def schedule_object_notification_deletion(instance, created, **kwargs):
    if instance.valid_till is not None:
        tasks.delete_ignore_object_notification.apply_async(
            (instance.pk,), eta=instance.valid_till
        )


def register_notification_cache_update(model, signal, dispatch_uid=None):
    signal.connect(
        update_notification_cache,
        sender=model,
        dispatch_uid=dispatch_uid,
    )


def update_notification_cache(sender, instance, **kwargs):
    def invalidate_cache():
        content_type = ContentType.objects.get_for_model(instance)
        cache_key = Notification._cache_key(content_type.id, instance.id)
        cache.delete(cache_key)

    # execute cache invalidation only after changes have been committed to the DB
    transaction.on_commit(invalidate_cache)
