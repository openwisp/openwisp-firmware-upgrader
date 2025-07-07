from datetime import timedelta

from celery import shared_task
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.db.utils import OperationalError
from django.utils import timezone

from openwisp_notifications import types
from openwisp_notifications.swapper import load_model, swapper_load_model
from openwisp_utils.tasks import OpenwispCeleryTask

User = get_user_model()

Notification = load_model('Notification')
NotificationSetting = load_model('NotificationSetting')
IgnoreObjectNotification = load_model('IgnoreObjectNotification')

Organization = swapper_load_model('openwisp_users', 'Organization')
OrganizationUser = swapper_load_model('openwisp_users', 'OrganizationUser')


@shared_task(base=OpenwispCeleryTask)
def delete_obsolete_objects(instance_app_label, instance_model, instance_id):
    """
    Delete Notification and IgnoreObjectNotification objects having
    instance' as related objects..
    """
    try:
        instance_content_type = ContentType.objects.get_by_natural_key(
            instance_app_label, instance_model
        )
    except ContentType.DoesNotExist:
        return
    else:
        # Delete Notification objects
        where = (
            Q(actor_content_type=instance_content_type)
            | Q(action_object_content_type=instance_content_type)
            | Q(target_content_type=instance_content_type)
        )
        where = where & (
            Q(actor_object_id=instance_id)
            | Q(action_object_object_id=instance_id)
            | Q(target_object_id=instance_id)
        )
        Notification.objects.filter(where).delete()

        # Delete IgnoreObjectNotification objects
        try:
            IgnoreObjectNotification.objects.filter(
                object_id=instance_id, object_content_type_id=instance_content_type.pk
            ).delete()
        except OperationalError:
            # Raised when an object is deleted in migration
            return


@shared_task(base=OpenwispCeleryTask)
def delete_notification(notification_id):
    Notification.objects.filter(pk=notification_id).delete()


@shared_task
def delete_old_notifications(days):
    """
    Delete notifications having 'timestamp' more than "days" days.
    """
    Notification.objects.filter(
        timestamp__lte=timezone.now() - timedelta(days=days)
    ).delete()


# Following tasks updates notification settings in database.
# 'ns' is short for notification_setting
def create_notification_settings(user, organizations, notification_types):
    for type in notification_types:
        for org in organizations:
            NotificationSetting.objects.update_or_create(
                defaults={'deleted': False}, user=user, type=type, organization=org
            )


@shared_task(base=OpenwispCeleryTask)
def update_superuser_notification_settings(instance_id, is_superuser, is_created=False):
    """
    NOTE: This task is deprecated and only kept for backward compatibility.
    It will be removed in 1.2.0 release.
    """
    if not is_superuser:
        superuser_demoted_notification_setting(instance_id)
    else:
        create_superuser_notification_settings(instance_id)


@shared_task(base=OpenwispCeleryTask)
def create_superuser_notification_settings(user_id):
    """
    Adds notification setting for all notification types and organizations.
    """
    user = User.objects.get(pk=user_id)
    # Create notification settings for superuser
    create_notification_settings(
        user=user,
        organizations=Organization.objects.all(),
        notification_types=types.NOTIFICATION_TYPES.keys(),
    )


@shared_task(base=OpenwispCeleryTask)
def superuser_demoted_notification_setting(user_id):
    """
    Flags NotificationSettings as deleted for non-managed organizations
    when a superuser is demoted to a non-superuser.
    """
    user = User.objects.get(pk=user_id)
    NotificationSetting.objects.filter(user_id=user_id).exclude(
        organization__in=user.organizations_managed
    ).update(deleted=True)


@shared_task(base=OpenwispCeleryTask)
def ns_register_unregister_notification_type(
    notification_type=None, delete_unregistered=True
):
    """
    Creates notification setting for registered notification types.
    Deletes notification for unregistered notification types.
    """

    notification_types = (
        [notification_type] if notification_type else types.NOTIFICATION_TYPES.keys()
    )

    organizations = Organization.objects.all()
    # Create notification settings for superusers
    for user in User.objects.filter(is_superuser=True).iterator():
        create_notification_settings(user, organizations, notification_types)

    # Create notification settings for organization admin
    for org_user in OrganizationUser.objects.select_related(
        'user', 'organization'
    ).filter(is_admin=True, user__is_superuser=False):
        create_notification_settings(
            org_user.user, [org_user.organization], notification_types
        )

    if delete_unregistered:
        # Delete all notification settings for unregistered notification types
        NotificationSetting.objects.exclude(type__in=notification_types).update(
            deleted=True
        )
        # Delete notifications related to unregister notification types
        Notification.objects.exclude(type__in=notification_types).delete()


@shared_task(base=OpenwispCeleryTask)
def update_org_user_notificationsetting(org_user_id, user_id, org_id, is_org_admin):
    """
    Adds notification settings for all notification types when a new
    organization user is added.
    """
    user = User.objects.get(pk=user_id)
    if not user.is_superuser:
        # The following query covers conditions for change in admin status
        # and organization field of related OrganizationUser objects
        NotificationSetting.objects.filter(user=user).exclude(
            organization_id__in=user.organizations_managed
        ).update(deleted=True)

    if not is_org_admin:
        return

    # Create new notification settings
    organization = Organization.objects.get(id=org_id)
    create_notification_settings(
        user=user,
        organizations=[organization],
        notification_types=types.NOTIFICATION_TYPES.keys(),
    )


@shared_task(base=OpenwispCeleryTask)
def ns_organization_user_deleted(user_id, org_id):
    """
    Deletes notification settings for all notification types when
    an organization user is deleted.
    """
    NotificationSetting.objects.filter(user_id=user_id, organization_id=org_id).update(
        deleted=True
    )


@shared_task(base=OpenwispCeleryTask)
def ns_organization_created(instance_id):
    """
    Adds notification setting of all registered types
    for a newly created organization.
    """
    organization = Organization.objects.get(id=instance_id)
    for user in User.objects.filter(is_superuser=True):
        create_notification_settings(
            user=user,
            organizations=[organization],
            notification_types=types.NOTIFICATION_TYPES.keys(),
        )


@shared_task(base=OpenwispCeleryTask)
def delete_ignore_object_notification(instance_id):
    """
    Deletes IgnoreObjectNotification object post it's expiration.
    """
    IgnoreObjectNotification.objects.filter(id=instance_id).delete()
