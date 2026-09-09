from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import reverse

from openwisp_firmware_upgrader import settings as app_settings
from openwisp_firmware_upgrader.api import views
from openwisp_firmware_upgrader.api.urls import get_api_urls
from openwisp_firmware_upgrader.urls import get_urls


class TestApiUrls(SimpleTestCase):
    def test_get_api_urls_uses_overrides_and_default_fallbacks(self):
        def custom_view():
            return None

        view_names = {
            "api_build_list": "build_list",
            "api_build_detail": "build_detail",
            "api_build_batch_upgrade": "api_batch_upgrade",
            "api_firmware_list": "firmware_image_list",
            "api_firmware_detail": "firmware_image_detail",
            "api_firmware_download": "firmware_image_download",
            "api_category_list": "category_list",
            "api_category_detail": "category_detail",
            "api_batchupgradeoperation_list": "batch_upgrade_operation_list",
            "api_batchupgradeoperation_detail": "batch_upgrade_operation_detail",
            "api_upgradeoperation_list": "upgrade_operation_list",
            "api_upgradeoperation_detail": "upgrade_operation_detail",
            "api_upgradeoperation_cancel": "upgrade_operation_cancel",
            "api_deviceupgradeoperation_list": "device_upgrade_operation_list",
            "api_devicefirmware_detail": "device_firmware_detail",
        }
        custom_views = SimpleNamespace(
            **{
                view_name: custom_view
                for view_name in view_names.values()
                if view_name != "device_firmware_detail"
            }
        )
        callbacks = {
            pattern.name: pattern.callback
            for pattern in get_api_urls(custom_views)[0].url_patterns
        }

        for url_name, view_name in view_names.items():
            with self.subTest(url_name=url_name):
                expected = (
                    views.device_firmware_detail
                    if view_name == "device_firmware_detail"
                    else custom_view
                )
                self.assertIs(callbacks[url_name], expected)

        default_callbacks = {
            pattern.name: pattern.callback for pattern in get_api_urls()[0].url_patterns
        }

        for url_name, view_name in view_names.items():
            with self.subTest(url_name=url_name, custom=False):
                self.assertIs(default_callbacks[url_name], getattr(views, view_name))


class TestUrls(SimpleTestCase):
    def test_get_urls_includes_private_storage_and_api_urls(self):
        urlpatterns = get_urls()
        self.assertEqual(len(urlpatterns), 2)
        self.assertEqual(urlpatterns[0].url_patterns[0].name, "serve_private_file")
        api_pattern = urlpatterns[1]
        self.assertEqual(api_pattern.pattern._route, "api/v1/")
        self.assertEqual(api_pattern.namespace, "upgrader")
        self.assertEqual(
            reverse("upgrader:api_build_list"),
            "/api/v1/firmware-upgrader/build/",
        )

    def test_get_urls_uses_overrides_and_default_fallbacks(self):
        def custom_view():
            return None

        custom_views = SimpleNamespace(build_list=custom_view)
        callbacks = {
            pattern.name: pattern.callback
            for pattern in get_urls(custom_views)[1].url_patterns[0].url_patterns
        }
        self.assertIs(callbacks["api_build_list"], custom_view)
        self.assertIs(callbacks["api_firmware_list"], views.firmware_image_list)

    def test_get_urls_with_api_disabled(self):
        with patch.object(app_settings, "FIRMWARE_UPGRADER_API", False):
            urlpatterns = get_urls()
        self.assertEqual(len(urlpatterns), 1)
        self.assertEqual(urlpatterns[0].url_patterns[0].name, "serve_private_file")
