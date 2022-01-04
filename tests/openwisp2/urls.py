from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path, reverse_lazy
from django.views.generic import RedirectView

from openwisp_users.api.urls import get_api_urls

redirect_view = RedirectView.as_view(url=reverse_lazy('admin:index'))

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', redirect_view, name='index'),
    path('', include('openwisp_controller.urls')),
    path('', include('openwisp_firmware_upgrader.urls')),
    # token auth API
    path('api/v1/', include((get_api_urls(), 'users'), namespace='users')),
    # needed for API docs
    path('api/v1/', include('openwisp_utils.api.urls')),
]

urlpatterns += staticfiles_urlpatterns()
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG and 'debug_toolbar' in settings.INSTALLED_APPS:
    import debug_toolbar

    urlpatterns.append(path('__debug__/', include(debug_toolbar.urls)))
