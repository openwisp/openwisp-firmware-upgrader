import os

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path, reverse_lazy
from django.views.generic import RedirectView

from openwisp_controller.connection.api.urls import (
    get_api_urls as get_connection_api_urls,
)
from openwisp_users.api.urls import get_api_urls

from .sample_connection.api import views as connection_api_views

redirect_view = RedirectView.as_view(url=reverse_lazy("admin:index"))

urlpatterns = []

if os.environ.get("SAMPLE_APP", False):
    urlpatterns += [
        path(
            "",
            include(("openwisp_controller.config.urls", "config"), namespace="config"),
        ),
        path(
            "api/v1/",
            include(
                (
                    get_connection_api_urls(connection_api_views),
                    "connection_api",
                ),
                namespace="connection_api",
            ),
        ),
    ]

urlpatterns += [
    path("admin/", admin.site.urls),
    path("", redirect_view, name="index"),
    path("", include("openwisp_controller.urls")),
    # path("accounts/", include("openwisp_users.accounts.urls")),   # Not needed in development
    path("", include("openwisp_firmware_upgrader.urls")),
    # token auth API
    path("api/v1/", include((get_api_urls(), "users"), namespace="users")),
    # needed for API docs
    path("api/v1/", include("openwisp_utils.api.urls")),
]

urlpatterns += staticfiles_urlpatterns()
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG and "debug_toolbar" in settings.INSTALLED_APPS:
    import debug_toolbar

    urlpatterns.append(path("__debug__/", include(debug_toolbar.urls)))
