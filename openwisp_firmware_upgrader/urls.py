from django.urls import include, path

from openwisp_firmware_upgrader import settings as app_settings

urlpatterns = [
    path('firmware/', include('openwisp_firmware_upgrader.private_storage.urls')),
]

if app_settings.FIRMWARE_UPGRADER_API:
    urlpatterns += [
        path('api/v1/', include('openwisp_firmware_upgrader.api.urls')),
    ]
