import uuid
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.forms.widgets import MediaOrderConflictWarning
from django.test import TestCase, override_settings, tag
from django.urls import reverse

from openwisp_notifications import settings as app_settings
from openwisp_notifications.admin import NotificationSettingInline
from openwisp_notifications.signals import notify
from openwisp_notifications.swapper import load_model, swapper_load_model
from openwisp_notifications.widgets import _add_object_notification_widget
from openwisp_users.admin import UserAdmin
from openwisp_users.tests.utils import TestMultitenantAdminMixin

from .test_helpers import MessagingRequest

Notification = load_model('Notification')
NotificationSetting = load_model('NotificationSetting')
notification_queryset = Notification.objects.order_by('-timestamp')
Group = swapper_load_model('openwisp_users', 'Group')


class MockUser:
    def __init__(self, is_superuser=False):
        self.is_superuser = is_superuser
        self.id = uuid.uuid4()

    def has_perm(self, perm):
        return True

    @property
    def pk(self):
        return self.id


User = get_user_model()
su_request = MessagingRequest()
su_request.user = MockUser(is_superuser=True)

op_request = MessagingRequest()
op_request.user = MockUser(is_superuser=False)


class BaseTestAdmin(TestMultitenantAdminMixin, TestCase):
    def _login_admin(self):
        u = User.objects.create_superuser('admin', 'admin', 'test@test.com')
        self.client.force_login(u)
        return u

    def setUp(self):
        self.admin = self._login_admin()
        self.notification_options = dict(
            sender=self.admin,
            recipient=self.admin,
            description='Test Notification',
            verb='Test Notification',
            email_subject='Test Email subject',
            url='localhost:8000/admin',
        )
        self.site = AdminSite()
        self.ns_inline = NotificationSettingInline(NotificationSetting, self.site)

    @property
    def _url(self):
        return reverse('admin:index')

    def _expected_output(self, count=None):
        if count:
            return '<span id="ow-notification-count">{0}</span>'.format(count)
        return 'id="openwisp_notifications">'


class TestAdmin(BaseTestAdmin):
    """
    Tests notifications in admin
    """

    app_label = 'openwisp_notifications'

    def test_zero_notifications(self):
        r = self.client.get(self._url)
        self.assertContains(r, self._expected_output())

    def test_non_zero_notifications(self):
        patched_function = 'openwisp_notifications.templatetags.notification_tags._get_user_unread_count'
        with self.subTest("Test UI for less than 100 notifications"):
            with patch(patched_function, return_value=10):
                r = self.client.get(self._url)
                self.assertContains(r, self._expected_output('10'))

        Notification.invalidate_unread_cache(self.admin)

        with self.subTest("Test UI for 99+ notifications"):
            with patch(patched_function, return_value=100):
                r = self.client.get(self._url)
                self.assertContains(r, self._expected_output('99+'))

    def test_cached_value(self):
        self.client.get(self._url)
        cache_key = Notification.count_cache_key(self.admin.pk)
        self.assertEqual(cache.get(cache_key), 0)
        return cache_key

    def test_cached_invalidation(self):
        cache_key = self.test_cached_value()
        notify.send(**self.notification_options)
        self.assertIsNone(cache.get(cache_key))
        self.client.get(self._url)
        self.assertEqual(cache.get(cache_key), 1)

    @tag('skip_prod')
    # This tests depends on the static storage backend of the project.
    # In prod environment, the filenames could get changed due to
    # static minification and cache invalidation. Hence, these tests
    # should not be run on prod environment because they'll fail.
    def test_default_notification_setting(self):
        res = self.client.get(self._url)
        self.assertContains(
            res, '/static/openwisp-notifications/audio/notification_bell.mp3'
        )
        self.assertContains(res, 'window.location')

    @tag('skip_prod')
    # For more info, look at TestAdmin.test_default_notification_setting
    @patch.object(
        app_settings,
        'SOUND',
        '/static/notification.mp3',
    )
    def test_notification_sound_setting(self):
        res = self.client.get(self._url)
        self.assertContains(res, '/static/notification.mp3')
        self.assertNotContains(
            res, '/static/openwisp-notifications/audio/notification_bell.mp3'
        )

    @patch.object(
        app_settings,
        'HOST',
        'https://example.com',
    )
    def test_notification_host_setting(self):
        res = self.client.get(self._url)
        self.assertContains(res, 'https://example.com')
        self.assertNotContains(res, 'window.location')

    def test_login_load_javascript(self):
        self.client.logout()
        response = self.client.get(reverse('admin:login'))
        self.assertNotContains(response, 'notifications.js')

    def test_websocket_protocol(self):
        with self.subTest('Test in production environment'):
            response = self.client.get(self._url)
            self.assertContains(response, 'wss')

    def test_notification_setting_inline_read_only_fields(self):
        with self.subTest('Test for superuser'):
            self.assertListEqual(self.ns_inline.get_readonly_fields(su_request), [])

        with self.subTest('Test for non-superuser'):
            self.assertListEqual(
                self.ns_inline.get_readonly_fields(op_request),
                ['type', 'organization'],
            )

    def test_notification_setting_inline_add_permission(self):
        with self.subTest('Test for superuser'):
            self.assertTrue(self.ns_inline.has_add_permission(su_request))

        with self.subTest('Test for non-superuser'):
            self.assertFalse(
                self.ns_inline.has_add_permission(op_request),
            )

    def test_notification_setting_inline_delete_permission(self):
        with self.subTest('Test for superuser'):
            self.assertTrue(self.ns_inline.has_delete_permission(su_request))

        with self.subTest('Test for non-superuser'):
            self.assertFalse(self.ns_inline.has_delete_permission(op_request))

    def test_notification_setting_inline_organization_formfield(self):
        response = self.client.get(
            reverse('admin:openwisp_users_user_change', args=(self.admin.pk,))
        )
        organization = self._get_org(org_name='default')
        self.assertContains(
            response,
            f'<option value="{organization.id}">{organization.name}</option>',
        )

    def test_notification_setting_inline_admin_has_change_permission(self):
        with self.subTest('Test for superuser'):
            self.assertTrue(
                self.ns_inline.has_change_permission(su_request),
            )

        with self.subTest('Test for non-superuser'):
            self.assertFalse(
                self.ns_inline.has_change_permission(op_request),
            )
            self.assertTrue(
                self.ns_inline.has_change_permission(op_request, obj=op_request.user),
            )

    def test_org_admin_view_same_org_user_notification_setting(self):
        org_owner = self._create_org_user(
            user=self._get_operator(),
            is_admin=True,
        )
        org_admin = self._create_org_user(
            user=self._create_user(
                username='user', email='user@user.com', is_staff=True
            ),
            is_admin=True,
        )
        permissions = Permission.objects.all()
        org_owner.user.user_permissions.set(permissions)
        org_admin.user.user_permissions.set(permissions)
        self.client.force_login(org_owner.user)

        response = self.client.get(
            reverse('admin:openwisp_users_user_change', args=(org_admin.user_id,)),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'User notification settings')
        self.assertNotContains(
            response, '<option value="default" selected>Default Type</option>'
        )

    def test_ignore_notification_widget_add_view(self):
        url = reverse('admin:openwisp_users_organization_add')
        response = self.client.get(url)
        self.assertNotContains(response, 'owIsChangeForm')


@tag('skip_prod')
# For more info, look at TestAdmin.test_default_notification_setting
class TestAdminMedia(BaseTestAdmin):
    """
    Tests notifications admin media
    """

    def test_jquery_import(self):
        response = self.client.get(self._url)
        self.assertInHTML(
            '<script src="/static/admin/js/jquery.init.js">',
            str(response.content),
            1,
        )
        self.assertInHTML(
            '<script src="/static/admin/js/vendor/jquery/jquery.min.js">',
            str(response.content),
            1,
        )

        response = self.client.get(reverse('admin:sites_site_changelist'))
        self.assertIn(
            '/static/admin/js/jquery.init.js',
            str(response.content),
            1,
        )
        self.assertIn(
            '/static/admin/js/vendor/jquery/jquery.min.js',
            str(response.content),
            1,
        )

    def test_object_notification_setting_empty(self):
        response = self.client.get(
            reverse('admin:openwisp_users_user_change', args=(self.admin.pk,))
        )
        self.assertNotContains(
            response, 'src="/static/openwisp-notifications/js/object-notifications.js"'
        )

    @override_settings(
        OPENWISP_NOTIFICATIONS_IGNORE_ENABLED_ADMIN=['openwisp_users.admin.UserAdmin'],
    )
    def test_object_notification_setting_configured(self):
        _add_object_notification_widget()
        response = self.client.get(
            reverse('admin:openwisp_users_user_change', args=(self.admin.pk,))
        )
        self.assertContains(
            response,
            'src="/static/openwisp-notifications/js/object-notifications.js"',
            1,
        )

        # If a ModelAdmin already has a Media class
        with self.assertWarns(MediaOrderConflictWarning):
            _add_object_notification_widget()
            response = self.client.get(
                reverse('admin:openwisp_users_user_change', args=(self.admin.pk,))
            )

        # If a ModelAdmin has list instances of js and css
        UserAdmin.Media.css = {'all': list()}
        UserAdmin.Media.js = list()
        _add_object_notification_widget()
        response = self.client.get(
            reverse('admin:openwisp_users_user_change', args=(self.admin.pk,))
        )

        # If ModelAdmin has empty attributes
        UserAdmin.Media.js = []
        UserAdmin.Media.css = {}
        _add_object_notification_widget()
        response = self.client.get(
            reverse('admin:openwisp_users_user_change', args=(self.admin.pk,))
        )
        UserAdmin.Media = None
