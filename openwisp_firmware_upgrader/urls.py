from django.urls import include, path

from openwisp_firmware_upgrader import settings as app_settings
from openwisp_firmware_upgrader.api import views as api_views
from openwisp_firmware_upgrader.api.urls import get_api_urls


def get_urls(api_views=api_views):
    urlpatterns = [
        path("", include("openwisp_firmware_upgrader.private_storage.urls")),
    ]
    if app_settings.FIRMWARE_UPGRADER_API:
        urlpatterns += [
            path(
                "api/v1/",
                include((get_api_urls(api_views), "upgrader"), namespace="upgrader"),
            ),
        ]
    return urlpatterns


urlpatterns = get_urls()
