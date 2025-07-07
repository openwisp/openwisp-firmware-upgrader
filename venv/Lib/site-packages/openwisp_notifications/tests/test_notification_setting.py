from unittest.mock import patch

from django.db.models.signals import post_save
from django.test import TransactionTestCase

from openwisp_notifications import tasks
from openwisp_notifications.handlers import (
    notification_type_registered_unregistered_handler,
)
from openwisp_notifications.swapper import load_model, swapper_load_model
from openwisp_notifications.tests.test_helpers import (
    base_register_notification_type,
    base_unregister_notification_type,
    mock_notification_types,
    register_notification_type,
)
from openwisp_users.tests.utils import TestOrganizationMixin

test_notification_type = {
    'verbose_name': 'Test Notification Type',
    'level': 'test',
    'verb': 'testing',
    'message': '{notification.verb} initiated by {notification.actor} since {notification}',
    'email_subject': '[{site.name}] {notification.verb} reported by {notification.actor}',
}

NotificationSetting = load_model('NotificationSetting')
Organization = swapper_load_model('openwisp_users', 'Organization')
OrganizationUser = swapper_load_model('openwisp_users', 'OrganizationUser')

ns_queryset = NotificationSetting.objects.filter(type='default')


class TestNotificationSetting(TestOrganizationMixin, TransactionTestCase):
    def setUp(self):
        self.default_org = self._get_org('default')

    def _create_staff_org_admin(self):
        return self._create_org_user(user=self._create_operator(), is_admin=True)

    def test_no_user(self):
        self.assertEqual(ns_queryset.count(), 0)

    def test_superuser_created(self):
        admin = self._get_admin()
        self.assertEqual(ns_queryset.filter(user=admin).count(), 1)

    def test_user_created(self):
        self._get_user()
        self.assertEqual(ns_queryset.count(), 0)

    @mock_notification_types
    def test_notification_type_registered(self):
        register_notification_type('test', test_notification_type)
        queryset = NotificationSetting.objects.filter(type='test')

        self._get_user()
        self.assertEqual(queryset.count(), 0)

        self._get_admin()
        self.assertEqual(queryset.count(), 1)
        self.assertEquals(
            queryset.first().__str__(), 'Test Notification Type - default'
        )

    def test_organization_created_no_initial_user(self):
        org = self._get_org()
        queryset = ns_queryset.filter(organization=org)
        self.assertEqual(ns_queryset.count(), 0)

        # Notification setting is not created for normal user
        self._get_user()
        self.assertEqual(queryset.count(), 0)

        self._get_admin()
        self.assertEqual(queryset.count(), 1)

    def test_organization_user(self):
        karen = self._get_user()
        ken = self._create_user(username='ken', email='ken@ken.com')
        org = self._get_org()
        OrganizationUser.objects.create(user=karen, organization=org, is_admin=True)
        org_user = OrganizationUser.objects.create(
            user=ken, organization=org, is_admin=True
        )
        self.assertEqual(ns_queryset.count(), 2)
        org_user.delete()
        # OrganizationOwner can not be deleted before transferring ownership
        self.assertEqual(ns_queryset.filter(deleted=False).count(), 1)
        self.assertEqual(ns_queryset.filter(deleted=True).count(), 1)

    @mock_notification_types
    def test_register_notification_org_user(self):
        self._create_staff_org_admin()

        queryset = NotificationSetting.objects.filter(type='test')
        self.assertEqual(queryset.count(), 0)
        register_notification_type('test', test_notification_type)
        self.assertEqual(queryset.count(), 1)

    @mock_notification_types
    def test_post_migration_handler(self):
        from openwisp_notifications.types import NOTIFICATION_CHOICES

        # Simulates loading of app when Django server starts
        admin = self._get_admin()
        org_user = self._create_staff_org_admin()
        self.assertEqual(ns_queryset.count(), 3)

        base_unregister_notification_type('default')
        base_register_notification_type('test', test_notification_type)
        notification_type_registered_unregistered_handler(sender=self)

        # Notification Setting for "default" type are deleted
        self.assertEqual(ns_queryset.filter(type='default', deleted=True).count(), 3)

        # Notification Settings for "test" type are created
        queryset = NotificationSetting.objects.filter(deleted=False)
        notification_types_count = len(NOTIFICATION_CHOICES)
        self.assertEqual(queryset.count(), 3 * notification_types_count)
        self.assertEqual(
            queryset.filter(user=admin).count(), 2 * notification_types_count
        )
        self.assertEqual(
            queryset.filter(user=org_user.user).count(), 1 * notification_types_count
        )

    def test_superuser_demoted_to_user(self):
        admin = self._get_admin()
        admin.is_superuser = False
        admin.save()

        self.assertEqual(ns_queryset.filter(deleted=True).count(), 1)

    def test_user_promoted_to_superuser(self):
        user = self._create_operator()
        self.assertEqual(ns_queryset.count(), 0)

        user.is_superuser = True
        user.save()

        self.assertEqual(ns_queryset.count(), 1)

    def test_superuser_demoted_to_org_admin(self):
        admin = self._get_admin()
        admin.is_superuser = False
        admin.save()
        org = Organization.objects.get(name='default')
        OrganizationUser.objects.create(user=admin, organization=org, is_admin=True)

        self.assertEqual(ns_queryset.count(), 1)

    def test_org_admin_demoted_to_org_user(self):
        org_user = self._create_staff_org_admin()
        self.assertEqual(ns_queryset.count(), 1)
        org_user.organizationowner.delete()
        org_user.is_admin = False
        org_user.full_clean()
        org_user.save()
        self.assertEqual(ns_queryset.filter(deleted=False).count(), 0)
        self.assertEqual(ns_queryset.filter(deleted=True).count(), 1)

    def test_org_user_promoted_to_org_admin(self):
        org_user = self._create_org_user(user=self._create_operator(), is_admin=False)
        self.assertEqual(ns_queryset.count(), 0)
        org_user.is_admin = True
        org_user.full_clean()
        org_user.save()
        self.assertEqual(ns_queryset.count(), 1)

    def test_multiple_org_membership(self):
        user = self._get_user()
        default_org = Organization.objects.first()
        test_org = self._get_org()
        self.assertEqual(ns_queryset.count(), 0)

        OrganizationUser.objects.create(
            user=user, organization=default_org, is_admin=True
        )
        self.assertEqual(ns_queryset.count(), 1)

        OrganizationUser.objects.create(user=user, organization=test_org, is_admin=True)
        self.assertEqual(ns_queryset.count(), 2)

    @mock_notification_types
    def test_notification_setting_full_clean(self):
        test_type = {
            'verbose_name': 'Test Notification Type',
            'level': 'info',
            'verb': 'testing',
            'message': 'Test message',
            'email_subject': 'Test Email Subject',
            'web_notification': False,
            'email_notification': False,
        }
        register_notification_type('test_type', test_type)
        self._get_admin()
        queryset = NotificationSetting.objects.filter(type='test_type')
        queryset.update(email=False, web=False)
        notification_setting = queryset.first()

        notification_setting.full_clean()
        self.assertIsNone(notification_setting.email)
        self.assertIsNone(notification_setting.web)

    def test_organization_user_updated(self):
        default_org = Organization.objects.first()
        org_user = self._create_staff_org_admin()
        self.assertNotEqual(org_user.organization_id, default_org.pk)
        self.assertEqual(ns_queryset.count(), 1)
        org_user.organization_id = default_org.pk
        org_user.full_clean()
        org_user.save()

        self.assertEqual(ns_queryset.filter(deleted=True).count(), 1)
        self.assertEqual(ns_queryset.filter(deleted=False).count(), 1)
        notification_setting = ns_queryset.first()
        self.assertEqual(notification_setting.organization.pk, default_org.pk)

    def test_organization_user_no_change_save(self):
        org_user = self._create_staff_org_admin()
        ns = ns_queryset.first()
        self.assertEqual(ns_queryset.count(), 1)
        org_user.full_clean()
        org_user.save()
        self.assertEqual(ns_queryset.count(), 1)
        update_ns = ns_queryset.first()
        self.assertEqual(ns.id, update_ns.id)

    def test_org_user_promoted_to_org_admin_with_org_change(self):
        default_org = Organization.objects.get(slug='default')
        org_user = self._create_org_user(user=self._create_operator(), is_admin=False)
        self.assertEqual(ns_queryset.count(), 0)
        org_user.is_admin = True
        org_user.organization = default_org
        org_user.full_clean()
        org_user.save()
        self.assertEqual(ns_queryset.count(), 1)
        ns = ns_queryset.first()
        self.assertEqual(ns.organization, default_org)
        self.assertEqual(ns.user, org_user.user)

    def test_deleted_notificationsetting_autocreated(self):
        org_user = self._create_staff_org_admin()
        self.assertEqual(ns_queryset.count(), 1)
        ns = ns_queryset.first()
        ns.deleted = True
        ns.full_clean()
        ns.save()

        # Emit post_save for organization user
        post_save.send(sender=OrganizationUser, instance=org_user, created=False)

        self.assertEqual(ns_queryset.count(), 1)
        ns.refresh_from_db()
        self.assertEqual(ns.deleted, False)

    @patch.object(tasks, 'superuser_demoted_notification_setting')
    @patch.object(tasks, 'create_superuser_notification_settings')
    def test_task_not_called_on_user_login(self, created_mock, demoted_mock):
        admin = self._create_admin()
        org_user = self._create_staff_org_admin()
        created_mock.delay.assert_called_once()

        created_mock.reset_mock()
        with self.subTest('Test task not called if superuser status is unchanged'):
            admin.username = 'new_admin'
            admin.save()
            created_mock.assert_not_called()
            demoted_mock.assert_not_called()

        with self.subTest('Test task not called when superuser logs in'):
            self.client.force_login(admin)
            created_mock.assert_not_called()
            demoted_mock.assert_not_called()

        with self.subTest('Test task not called when org user logs in'):
            self.client.force_login(org_user.user)
            created_mock.assert_not_called()
            demoted_mock.assert_not_called()

        with self.subTest('Test task called when superuser status changed'):
            admin.is_superuser = False
            admin.save()
            demoted_mock.assert_called_once()
            created_mock.assert_not_called()

            admin.is_superuser = True
            admin.save()
            created_mock.assert_called_once()
