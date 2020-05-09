from django.conf.urls import url
from django.urls import path
from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from openwisp_firmware_upgrader import settings as app_settings
from rest_framework import permissions

from . import views

app_name = 'upgrader'

urlpatterns = []

if app_settings.FIRMWARE_UPGRADER_API:

    schema_view = get_schema_view(
        openapi.Info(
            title='Firmware Upgrader API',
            default_version='v1',
            description='OpenWISP Firmware Upgrader API',
            contact=openapi.Contact(email='openwisp@googlegroups.com'),
            license=openapi.License(name="GPLv3"),
        ),
        public=True,
        permission_classes=(permissions.AllowAny,),
    )

    urlpatterns += [
        # Swagger
        url(
            r'^swagger(?P<format>\.json|\.yaml)$',
            schema_view.without_ui(cache_timeout=0),
            name='schema-json',
        ),
        url(
            r'^swagger/$',
            schema_view.with_ui('swagger', cache_timeout=0),
            name='schema-swagger-ui',
        ),
        url(
            r'^redoc/$',
            schema_view.with_ui('redoc', cache_timeout=0),
            name='schema-redoc',
        ),
        # API endpoints
        path('firmware/build/', views.build_list, name='api_build_list'),
        path('firmware/build/<pk>/', views.build_detail, name='api_build_detail'),
        path(
            'firmware/build/<pk>/image/',
            views.firmware_image_list,
            name='api_firmware_list',
        ),
        path(
            'firmware/build/<build_pk>/image/<pk>/',
            views.firmware_image_detail,
            name='api_firmware_detail',
        ),
        path(
            'firmware/build/<build_pk>/image/<pk>/download/',
            views.firmware_image_download,
            name='api_firmware_download',
        ),
        path('firmware/category/', views.category_list, name='api_category_list'),
        path(
            'firmware/category/<pk>/',
            views.category_detail,
            name='api_category_detail',
        ),
        path(
            'firmware/batch-upgrade-operation/',
            views.batch_upgrade_operation_list,
            name='api_batchupgradeoperation_list',
        ),
        path(
            'firmware/batch-upgrade-operation/<pk>/',
            views.batch_upgrade_operation_detail,
            name='api_batchupgradeoperation_detail',
        ),
    ]
