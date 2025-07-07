import uuid
from datetime import datetime
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import ErrorDetail

from openwisp_notifications.signals import notify
from openwisp_notifications.swapper import load_model, swapper_load_model
from openwisp_notifications.tests.test_helpers import (
    TEST_DATETIME,
    mock_notification_types,
    register_notification_type,
)
from openwisp_users.tests.test_api import AuthenticationMixin
from openwisp_users.tests.utils import TestOrganizationMixin
from openwisp_utils.tests import capture_any_output

Notification = load_model('Notification')
NotificationSetting = load_model('NotificationSetting')
IgnoreObjectNotification = load_model('IgnoreObjectNotification')

Organization = swapper_load_model('openwisp_users', 'Organization')
OrganizationUser = swapper_load_model('openwisp_users', 'OrganizationUser')


class TestNotificationApi(
    TransactionTestCase, TestOrganizationMixin, AuthenticationMixin
):
    url_namespace = 'notifications'

    def setUp(self):
        self.admin = self._get_admin(self)
        if not Organization.objects.first():
            self._create_org(name='default', slug='default')
        self.client.force_login(self.admin)

    def _get_path(self, url_name, *args, **kwargs):
        path = reverse(f'{self.url_namespace}:{url_name}', args=args)
        if not kwargs:
            return path
        query_params = []
        for key, value in kwargs.items():
            query_params.append(f'{key}={value}')
        query_string = '&'.join(query_params)
        return f'{path}?{query_string}'

    def _create_ignore_obj_notification(self):
        org_user = self._get_org_user()
        org_user_content_type_id = ContentType.objects.get_for_model(
            org_user._meta.model
        ).pk
        ignore_obj_notification = IgnoreObjectNotification.objects.create(
            user=self.admin,
            object_id=org_user.pk,
            object_content_type_id=org_user_content_type_id,
            valid_till=TEST_DATETIME,
        )
        return (
            ignore_obj_notification,
            org_user._meta.app_label,
            org_user._meta.model_name,
            org_user.pk,
        )

    def test_list_notification_api(self):
        number_of_notifications = 21
        url = reverse(f'{self.url_namespace}:notifications_list')
        for _ in range(number_of_notifications):
            notify.send(sender=self.admin, type='default', target=self.admin)

        with self.subTest('Test "page" query in notification list view'):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data['count'], number_of_notifications)
            self.assertIn(
                self._get_path('notifications_list', page=2),
                response.data['next'],
            )
            self.assertEqual(response.data['previous'], None)
            self.assertEqual(len(response.data['results']), 20)

            next_response = self.client.get(response.data['next'])
            self.assertEqual(next_response.status_code, 200)
            self.assertEqual(next_response.data['count'], number_of_notifications)
            self.assertEqual(
                next_response.data['next'],
                None,
            )
            self.assertIn(
                self._get_path('notifications_list'),
                next_response.data['previous'],
            )
            self.assertEqual(len(next_response.data['results']), 1)

        with self.subTest('Test "page_size" query'):
            page_size = 5
            url = f'{url}?page_size={page_size}'
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data['count'], number_of_notifications)
            self.assertIn(
                self._get_path('notifications_list', page=2, page_size=page_size),
                response.data['next'],
            )
            self.assertEqual(response.data['previous'], None)
            self.assertEqual(len(response.data['results']), page_size)

            next_response = self.client.get(response.data['next'])
            self.assertEqual(next_response.status_code, 200)
            self.assertEqual(next_response.data['count'], number_of_notifications)
            self.assertIn(
                self._get_path('notifications_list', page=3, page_size=page_size),
                next_response.data['next'],
            )
            self.assertIn(
                self._get_path('notifications_list', page_size=page_size),
                next_response.data['previous'],
            )
            self.assertEqual(len(next_response.data['results']), page_size)

        with self.subTest('Test individual result object'):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            n = response.data['results'][0]
            self.assertIn('id', n)
            self.assertIn('message', n)
            self.assertTrue(n['unread'])
            self.assertIn('target_url', n)
            self.assertEqual(
                n['email_subject'], '[example.com] Default Notification Subject'
            )

    def test_list_notification_filtering(self):
        url = self._get_path('notifications_list')
        notify.send(sender=self.admin, type='default', target=self.admin)
        notify.send(sender=self.admin, type='default', target=self.admin)
        # Mark one notification as read
        n_read = Notification.objects.first()
        n_read.mark_as_read()

        with self.subTest('Test listing notifications without filters'):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.data['results']), 2)

        with self.subTest('Test listing read notifications'):
            read_url = f'{url}?unread=false'
            response = self.client.get(read_url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.data['results']), 1)
            n = response.data['results'].pop()
            self.assertEqual(n['id'], str(n_read.id))
            self.assertFalse(n['unread'])

        with self.subTest('Test listing unread notifications'):
            unread_url = f'{url}?unread=true'
            response = self.client.get(unread_url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.data['results']), 1)
            n = response.data['results'].pop()
            self.assertNotEqual(n['id'], str(n_read.id))
            self.assertTrue(n['unread'])

    def test_notifications_read_all_api(self):
        number_of_notifications = 2
        for _ in range(number_of_notifications):
            notify.send(sender=self.admin, type='default', target=self.admin)

        url = self._get_path('notifications_read_all')
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data)
        # Verify notifications are marked read in database
        for n in Notification.objects.all():
            self.assertFalse(n.unread)

    def test_retreive_notification_api(self):
        notify.send(sender=self.admin, type='default', target=self.admin)
        n = Notification.objects.first()

        with self.subTest('Test for non-existing notification'):
            url = self._get_path('notification_detail', uuid.uuid4())
            response = self.client.get(url)
            self.assertEqual(response.status_code, 404)

        with self.subTest('Test retrieving details for existing notification'):
            url = self._get_path('notification_detail', n.pk)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            data = response.data
            self.assertEqual(data['id'], str(n.id))
            self.assertEqual(data['message'], n.message)
            self.assertEqual(data['email_subject'], n.email_subject)
            self.assertEqual(data['unread'], n.unread)

    def test_read_single_notification_api(self):
        notify.send(sender=self.admin, type='default', target=self.admin)
        n = Notification.objects.first()

        with self.subTest('Test for non-existing notification'):
            url = self._get_path('notification_detail', uuid.uuid4())
            response = self.client.patch(url)
            self.assertEqual(response.status_code, 404)

        with self.subTest('Test for existing notification'):
            self.assertTrue(n.unread)
            url = self._get_path('notification_detail', n.pk)
            response = self.client.patch(url)
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(response.data)
            n = Notification.objects.first()
            self.assertEqual(n.unread, False)

    def test_notification_delete_api(self):
        notify.send(sender=self.admin, type='default', target=self.admin)
        n = Notification.objects.first()

        with self.subTest('Test for non-existing notification'):
            url = self._get_path('notification_detail', uuid.uuid4())
            response = self.client.delete(url)
            self.assertEqual(response.status_code, 404)

        with self.subTest('Test for valid notification'):
            url = self._get_path('notification_detail', n.pk)
            response = self.client.delete(url)
            self.assertEqual(response.status_code, 204)
            self.assertIsNone(response.data)
            self.assertFalse(Notification.objects.all())

    def test_anonymous_user(self):
        response_data = {
            'detail': ErrorDetail(
                string='Authentication credentials were not provided.',
                code='not_authenticated',
            )
        }

        self.client.logout()

        with self.subTest('Test for list notifications API'):
            url = self._get_path('notifications_list')
            response = self.client.get(url)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.data, response_data)

        with self.subTest('Test for notification detail API'):
            url = self._get_path('notification_detail', uuid.uuid4())
            response = self.client.get(url)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.data, response_data)

    @patch('openwisp_notifications.tasks.delete_ignore_object_notification.apply_async')
    def test_bearer_authentication(self, mocked_test):
        self.client.logout()
        notify.send(sender=self.admin, type='default', target=self._get_org_user())
        n = Notification.objects.first()
        notification_setting = NotificationSetting.objects.first()
        notification_setting_count = NotificationSetting.objects.count()
        token = self._obtain_auth_token(username='admin', password='tester')

        with self.subTest('Test listing all notifications'):
            url = self._get_path('notifications_list')
            response = self.client.get(url, HTTP_AUTHORIZATION=f'Bearer {token}')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.data['results']), 1)

        with self.subTest('Test marking all notifications as read'):
            url = self._get_path('notifications_read_all')
            response = self.client.post(url, HTTP_AUTHORIZATION=f'Bearer {token}')
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(response.data)

        with self.subTest('Test retrieving notification'):
            url = self._get_path('notification_detail', n.pk)
            response = self.client.get(url, HTTP_AUTHORIZATION=f'Bearer {token}')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data['id'], str(n.id))

        with self.subTest('Test marking a notification as read'):
            url = self._get_path('notification_detail', n.pk)
            response = self.client.patch(url, HTTP_AUTHORIZATION=f'Bearer {token}')
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(response.data)

        with self.subTest('Test redirect read view'):
            url = self._get_path('notification_read_redirect', n.pk)
            response = self.client.get(url, HTTP_AUTHORIZATION=f'Bearer {token}')
            self.assertEqual(response.status_code, 302)

        with self.subTest('Test deleting notification'):
            url = self._get_path('notification_detail', n.pk)
            response = self.client.delete(url, HTTP_AUTHORIZATION=f'Bearer {token}')
            self.assertEqual(response.status_code, 204)
            self.assertIsNone(response.data)

        with self.subTest('Test listing notification settings'):
            url = self._get_path('notification_setting_list')
            response = self.client.get(url, HTTP_AUTHORIZATION=f'Bearer {token}')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.data['results']), notification_setting_count)

        with self.subTest('Test retrieving notification setting'):
            url = self._get_path('notification_setting', notification_setting.pk)
            response = self.client.get(url, HTTP_AUTHORIZATION=f'Bearer {token}')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data['id'], str(notification_setting.id))

        with self.subTest('Test updating notification setting'):
            url = self._get_path('notification_setting', notification_setting.pk)
            response = self.client.put(
                url,
                data={'web': False},
                content_type='application/json',
                HTTP_AUTHORIZATION=f'Bearer {token}',
            )
            self.assertEqual(response.status_code, 200)
            self.assertIsNotNone(response.data)

        (
            obj_notification,
            obj_app_label,
            obj_model_name,
            obj_id,
        ) = self._create_ignore_obj_notification()

        with self.subTest('Test listing object notifications'):
            url = self._get_path('ignore_object_notification_list')
            response = self.client.get(url, HTTP_AUTHORIZATION=f'Bearer {token}')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.data['results']), 1)

        with self.subTest('Test retrieving ignore_obj_notification'):
            url = self._get_path(
                'ignore_object_notification', obj_app_label, obj_model_name, obj_id
            )
            response = self.client.get(url, HTTP_AUTHORIZATION=f'Bearer {token}')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data['object_id'], str(obj_id))

        with self.subTest('Test creating notification setting'):
            url = self._get_path(
                'ignore_object_notification', obj_app_label, obj_model_name, obj_id
            )
            response = self.client.put(
                url,
                HTTP_AUTHORIZATION=f'Bearer {token}',
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn('id', response.data)

        with self.subTest('Test deleting ignore_obj_notification'):
            url = self._get_path(
                'ignore_object_notification', obj_app_label, obj_model_name, obj_id
            )
            response = self.client.delete(url, HTTP_AUTHORIZATION=f'Bearer {token}')
            self.assertEqual(response.status_code, 204)

    def test_notification_recipients(self):
        # Tests user can only interact with notifications assigned to them
        self.client.logout()
        joe = self._create_user(username='joe', email='joe@joe.com')
        karen = self._create_user(username='karen', email='karen@karen.com')
        notify.send(sender=self.admin, type='default', recipient=karen)
        n = Notification.objects.first()
        self.client.force_login(joe)

        with self.subTest('Test listing all notifications'):
            url = self._get_path('notifications_list')
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data['count'], 0)
            self.assertEqual(len(response.data['results']), 0)
            self.assertEqual(response.data['next'], None)

        with self.subTest('Test marking all notifications as read'):
            url = self._get_path('notifications_read_all')
            response = self.client.post(url)
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(response.data)
            # Check Karen's notification is still unread
            n.refresh_from_db()
            self.assertTrue(n.unread)

        with self.subTest('Test retrieving notification'):
            url = self._get_path('notification_detail', n.pk)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 404)

        with self.subTest('Test marking a notification as read'):
            url = self._get_path('notification_detail', n.pk)
            response = self.client.patch(url)
            self.assertEqual(response.status_code, 404)
            # Check Karen's notification is still unread
            n.refresh_from_db()
            self.assertTrue(n.unread)

        with self.subTest('Test deleting notification'):
            url = self._get_path('notification_detail', n.pk)
            response = self.client.delete(url)
            self.assertEqual(response.status_code, 404)
            # Check Karen's notification is not deleted
            self.assertEqual(Notification.objects.count(), 1)

    def test_list_view_notification_cache(self):
        number_of_notifications = 5
        url = self._get_path('notifications_list', page_size=number_of_notifications)
        operator = self._get_operator()
        for _ in range(number_of_notifications):
            notify.send(sender=self.admin, type='default', target=operator)

        with self.assertNumQueries(3):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data['count'], number_of_notifications)

    @capture_any_output()
    @mock_notification_types
    def test_malformed_notifications(self):
        test_type = {
            'verbose_name': 'Test Notification Type',
            'level': 'warning',
            'verb': 'testing',
            'message': '{notification.actor.random}',
            'email_subject': '[{site.name}] {notification.actor.random}',
        }
        register_notification_type('test_type', test_type)

        with self.subTest('Test list notifications'):
            notify.send(sender=self.admin, type='default')
            notify.send(sender=self.admin, type='test_type')
            url = self._get_path('notifications_list')
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data['count'], 1)
            self.assertEqual(
                response.data['next'],
                None,
            )
            self.assertEqual(response.data['previous'], None)
            self.assertEqual(len(response.data['results']), 1)

        with self.subTest('Test retrieve notification'):
            [(_, [n])] = notify.send(
                sender=self.admin, type='test_type', target=self._get_org_user()
            )
            url = self._get_path('notification_detail', n.pk)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 404)

    @capture_any_output()
    @mock_notification_types
    @patch('openwisp_notifications.tasks.delete_obsolete_objects.delay')
    def test_obsolete_notifications_busy_worker(self, mocked_task):
        """
        This test simulates deletion of related object when all celery
        workers are busy and related objects are not cached.
        """
        operator = self._get_operator()
        test_type = {
            'verbose_name': 'Test Notification Type',
            'level': 'warning',
            'verb': 'testing',
            'message': 'Test notification for {notification.target.pk}',
            'email_subject': '[{site.name}] {notification.target.pk}',
        }
        register_notification_type('test_type', test_type)

        notify.send(sender=self.admin, type='test_type', target=operator)
        notification = Notification.objects.first()
        self.assertEqual(
            notification.message, f'<p>Test notification for {operator.pk}</p>'
        )
        operator.delete()
        notification.refresh_from_db()

        # Delete target object from cache
        cache_key = Notification._cache_key(
            notification.target_content_type_id, notification.target_object_id
        )
        cache.delete(cache_key)
        self.assertIsNone(cache.get(cache_key))

        with self.subTest('Test list notifications'):
            url = self._get_path('notifications_list')
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data['count'], 1)
            self.assertFalse(response.data['results'])

        with self.subTest('Test retrieve notification'):
            url = self._get_path('notification_read_redirect', notification.pk)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 404)

    def test_notification_setting_list_api(self):
        self._create_org_user(is_admin=True)
        number_of_settings = NotificationSetting.objects.filter(user=self.admin).count()
        url = self._get_path('notification_setting_list')

        with self.subTest('Test notification setting list view'):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data['count'], number_of_settings)
            self.assertEqual(
                response.data['next'],
                None,
            )
            self.assertEqual(response.data['previous'], None)
            self.assertEqual(len(response.data['results']), number_of_settings)

        with self.subTest('Test "page_size" query'):
            page_size = 2
            url = f'{url}?page_size={page_size}'
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data['count'], number_of_settings)
            self.assertIn(
                self._get_path(
                    'notification_setting_list', page=2, page_size=page_size
                ),
                response.data['next'],
            )
            self.assertEqual(response.data['previous'], None)
            self.assertEqual(len(response.data['results']), page_size)

            next_response = self.client.get(response.data['next'])
            self.assertEqual(next_response.status_code, 200)
            self.assertEqual(next_response.data['count'], number_of_settings)
            self.assertIn(
                self._get_path('notification_setting_list', page_size=page_size),
                next_response.data['previous'],
            )
            self.assertEqual(len(next_response.data['results']), page_size)
            if NotificationSetting._meta.app_label == 'sample_notifications':
                self.assertIn(
                    self._get_path(
                        'notification_setting_list', page=3, page_size=page_size
                    ),
                    next_response.data['next'],
                )
            else:
                self.assertIsNone(next_response.data['next'])

        with self.subTest('Test individual result object'):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            notification_setting = response.data['results'][0]
            self.assertIn('id', notification_setting)
            self.assertIsNone(notification_setting['web'])
            self.assertIsNone(notification_setting['email'])
            self.assertIn('organization', notification_setting)

    def test_list_notification_setting_filtering(self):
        url = self._get_path('notification_setting_list')

        with self.subTest('Test listing notification setting without filters'):
            count = NotificationSetting.objects.count()
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.data['results']), count)

        with self.subTest('Test listing notification setting for "default" org'):
            org = Organization.objects.first()
            count = NotificationSetting.objects.filter(organization_id=org.id).count()
            org_url = f'{url}?organization={org.id}'
            response = self.client.get(org_url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.data['results']), count)
            ns = response.data['results'].pop()
            self.assertEqual(ns['organization'], org.id)

        with self.subTest('Test listing notification setting for "default" org slug'):
            org = Organization.objects.first()
            count = NotificationSetting.objects.filter(organization=org).count()
            org_slug_url = f'{url}?organization_slug={org.slug}'
            response = self.client.get(org_slug_url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.data['results']), count)
            ns = response.data['results'].pop()
            self.assertEqual(ns['organization'], org.id)

        with self.subTest('Test listing notification for "default" type'):
            type_url = f'{url}?type=default'
            response = self.client.get(type_url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.data['results']), 1)
            ns = response.data['results'].pop()
            self.assertEqual(ns['type'], 'default')

    def test_retreive_notification_setting_api(self):
        notification_setting = NotificationSetting.objects.first()

        with self.subTest('Test for non-existing notification setting'):
            url = self._get_path('notification_setting', uuid.uuid4())
            response = self.client.get(url)
            self.assertEqual(response.status_code, 404)

        with self.subTest('Test retrieving details for existing notification setting'):
            url = self._get_path(
                'notification_setting',
                notification_setting.pk,
            )
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            data = response.data
            self.assertEqual(data['id'], str(notification_setting.id))
            self.assertEqual(data['organization'], notification_setting.organization.pk)
            self.assertEqual(data['web'], notification_setting.web)
            self.assertEqual(data['email'], notification_setting.email)

    def test_update_notification_setting_api(self):
        notification_setting = NotificationSetting.objects.first()
        update_data = {'web': False}

        with self.subTest('Test for non-existing notification setting'):
            url = self._get_path('notification_setting', uuid.uuid4())
            response = self.client.put(url, data=update_data)
            self.assertEqual(response.status_code, 404)

        with self.subTest('Test retrieving details for existing notification setting'):
            url = self._get_path(
                'notification_setting',
                notification_setting.pk,
            )
            response = self.client.put(
                url, update_data, content_type='application/json'
            )
            self.assertEqual(response.status_code, 200)
            data = response.data
            notification_setting.refresh_from_db()
            self.assertEqual(data['id'], str(notification_setting.id))
            self.assertEqual(data['organization'], notification_setting.organization.pk)
            self.assertEqual(data['web'], notification_setting.web)
            self.assertEqual(data['email'], notification_setting.email)

    def test_notification_redirect_api(self):
        def _unread_notification(notification):
            notification.unread = True
            notification.save()

        notify.send(sender=self.admin, type='default', target=self.admin)
        notification = Notification.objects.first()

        with self.subTest('Test non-existent notification'):
            url = self._get_path('notification_read_redirect', uuid.uuid4())
            response = self.client.get(url)
            self.assertEqual(response.status_code, 404)

        with self.subTest('Test existent notification'):
            url = self._get_path('notification_read_redirect', notification.pk)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, notification.target_url)
            notification.refresh_from_db()
            self.assertEqual(notification.unread, False)

        _unread_notification(notification)

        with self.subTest('Test user not logged in'):
            self.client.logout()
            url = self._get_path('notification_read_redirect', notification.pk)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(
                response.url,
                '{view}?next={url}'.format(view=reverse('admin:login'), url=url),
            )

    @patch('openwisp_notifications.tasks.delete_ignore_object_notification.apply_async')
    def test_create_ignore_obj_notification_api(self, mocked_task):
        org_user = self._get_org_user()
        org_user_content_type_id = ContentType.objects.get_for_model(
            org_user._meta.model
        ).pk
        url = self._get_path(
            'ignore_object_notification',
            org_user._meta.app_label,
            org_user._meta.model_name,
            org_user.pk,
        )

        response = self.client.put(
            url, data={'valid_till': TEST_DATETIME}, content_type='application/json'
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(IgnoreObjectNotification.objects.count(), 1)

        ignore_obj_notification = IgnoreObjectNotification.objects.first()
        self.assertEqual(ignore_obj_notification.user_id, self.admin.pk)
        self.assertEqual(ignore_obj_notification.object_id, str(org_user.pk))
        self.assertEqual(
            ignore_obj_notification.object_content_type_id, org_user_content_type_id
        )
        self.assertEqual(ignore_obj_notification.valid_till, TEST_DATETIME)

    @patch('openwisp_notifications.tasks.delete_ignore_object_notification.apply_async')
    def test_update_ignore_obj_notification_api(self, mocked_task):
        (
            obj_notification,
            obj_app_label,
            obj_model_name,
            obj_id,
        ) = self._create_ignore_obj_notification()
        self.assertEqual(IgnoreObjectNotification.objects.count(), 1)

        valid_till = datetime(2020, 8, 31, 0, 0, 0, 0, timezone.get_default_timezone())
        url = self._get_path(
            'ignore_object_notification', obj_app_label, obj_model_name, obj_id
        )

        response = self.client.put(
            url, data={'valid_till': valid_till}, content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(IgnoreObjectNotification.objects.count(), 1)
        ignore_obj_notification = IgnoreObjectNotification.objects.first()
        self.assertEqual(ignore_obj_notification.valid_till, valid_till)

    @patch('openwisp_notifications.tasks.delete_ignore_object_notification.apply_async')
    def test_delete_ignore_obj_notification_api(self, mocked_task):
        (
            obj_notification,
            obj_app_label,
            obj_model_name,
            obj_id,
        ) = self._create_ignore_obj_notification()

        with self.subTest('Test for non-existing object notification'):
            url = self._get_path(
                'ignore_object_notification',
                obj_app_label,
                obj_model_name,
                uuid.uuid4(),
            )
            response = self.client.delete(url)
            self.assertEqual(response.status_code, 404)

        with self.subTest('Test for existing object notification'):
            url = self._get_path(
                'ignore_object_notification', obj_app_label, obj_model_name, obj_id
            )
            response = self.client.delete(url)
            self.assertEqual(response.status_code, 204)
            self.assertIsNone(response.data)
            self.assertEqual(IgnoreObjectNotification.objects.count(), 0)

    @patch('openwisp_notifications.tasks.delete_ignore_object_notification.apply_async')
    def test_retrieve_ignore_obj_notification_api(self, mocked_task):
        (
            obj_notification,
            obj_app_label,
            obj_model_name,
            obj_id,
        ) = self._create_ignore_obj_notification()

        with self.subTest('Test for non-existing object notification'):
            url = self._get_path(
                'ignore_object_notification',
                obj_app_label,
                obj_model_name,
                uuid.uuid4(),
            )
            response = self.client.delete(url)
            self.assertEqual(response.status_code, 404)

        with self.subTest('Test for existing object notification'):
            url = self._get_path(
                'ignore_object_notification', obj_app_label, obj_model_name, obj_id
            )
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('user', response.data)
            self.assertIn('id', response.data)
            self.assertIn('object_id', response.data)
            self.assertIn('object_content_type', response.data)
            self.assertIn('valid_till', response.data)

    @patch('openwisp_notifications.tasks.delete_ignore_object_notification.apply_async')
    def test_list_ignore_obj_notification_api(self, mocked_task):
        number_of_obj_notifications = 21
        url = reverse(f'{self.url_namespace}:ignore_object_notification_list')
        ignore_obj_notifications = []
        content_type = ContentType.objects.filter(
            app_label='openwisp_users', model='user'
        ).first()
        for _ in range(number_of_obj_notifications):
            ignore_obj_notifications.append(
                IgnoreObjectNotification(
                    user=self.admin,
                    object_id=uuid.uuid4(),
                    object_content_type_id=content_type.id,
                )
            )
        IgnoreObjectNotification.objects.bulk_create(
            ignore_obj_notifications, ignore_conflicts=False
        )
        self.assertEqual(
            IgnoreObjectNotification.objects.count(), number_of_obj_notifications
        )

        with self.subTest('Test "page" query in object notification list view'):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data['count'], number_of_obj_notifications)
            self.assertIn(
                self._get_path('ignore_object_notification_list', page=2),
                response.data['next'],
            )
            self.assertEqual(response.data['previous'], None)
            self.assertEqual(len(response.data['results']), 20)

            next_response = self.client.get(response.data['next'])
            self.assertEqual(next_response.status_code, 200)
            self.assertEqual(next_response.data['count'], number_of_obj_notifications)
            self.assertEqual(
                next_response.data['next'],
                None,
            )
            self.assertIn(
                self._get_path('ignore_object_notification_list'),
                next_response.data['previous'],
            )
            self.assertEqual(len(next_response.data['results']), 1)

        with self.subTest('Test "page_size" query'):
            page_size = 5
            url = f'{url}?page_size={page_size}'
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data['count'], number_of_obj_notifications)
            self.assertIn(
                self._get_path(
                    'ignore_object_notification_list', page=2, page_size=page_size
                ),
                response.data['next'],
            )
            self.assertEqual(response.data['previous'], None)
            self.assertEqual(len(response.data['results']), page_size)

            next_response = self.client.get(response.data['next'])
            self.assertEqual(next_response.status_code, 200)
            self.assertEqual(next_response.data['count'], number_of_obj_notifications)
            self.assertIn(
                self._get_path(
                    'ignore_object_notification_list', page=3, page_size=page_size
                ),
                next_response.data['next'],
            )
            self.assertIn(
                self._get_path('ignore_object_notification_list', page_size=page_size),
                next_response.data['previous'],
            )
            self.assertEqual(len(next_response.data['results']), page_size)

        with self.subTest('Test individual result object'):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            ignore_obj_notification = response.data['results'][0]
            self.assertIn('id', ignore_obj_notification)
            self.assertIn('object_id', ignore_obj_notification)
            self.assertIn('object_content_type', ignore_obj_notification)
            self.assertIsNone(ignore_obj_notification['valid_till'])

    @capture_any_output()
    @patch('openwisp_notifications.tasks.delete_notification.delay')
    def test_deleted_notification_type(self, *args):
        notify.send(sender=self.admin, type='default', target=self.admin)
        with patch('openwisp_notifications.types.NOTIFICATION_TYPES', {}):
            url = self._get_path('notifications_list')
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.data['results']), 0)
            self.assertEqual(Notification.objects.count(), 1)

            notification = Notification.objects.first()
            url = self._get_path('notification_detail', notification.pk)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 404)
