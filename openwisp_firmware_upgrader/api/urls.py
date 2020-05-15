from django.conf.urls import url
from django.urls import include, path
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
        path(
            'firmware/',
            include(
                [
                    path('build/', views.build_list, name='api_build_list'),
                    path('build/<pk>/', views.build_detail, name='api_build_detail'),
                    path(
                        'build/<pk>/image/',
                        views.firmware_image_list,
                        name='api_firmware_list',
                    ),
                    path(
                        'build/<build_pk>/image/<pk>/',
                        views.firmware_image_detail,
                        name='api_firmware_detail',
                    ),
                    path(
                        'build/<build_pk>/image/<pk>/download/',
                        views.firmware_image_download,
                        name='api_firmware_download',
                    ),
                    path('category/', views.category_list, name='api_category_list'),
                    path(
                        'category/<pk>/',
                        views.category_detail,
                        name='api_category_detail',
                    ),
                    path(
                        'batch-upgrade-operation/',
                        views.batch_upgrade_operation_list,
                        name='api_batchupgradeoperation_list',
                    ),
                    path(
                        'batch-upgrade-operation/<pk>/',
                        views.batch_upgrade_operation_detail,
                        name='api_batchupgradeoperation_detail',
                    ),
                ]
            ),
        ),
    ]
