from django.urls import path
from openwisp_firmware_upgrader import settings as app_settings

from . import views

app_name = 'upgrader'

urlpatterns = []

if app_settings.FIRMWARE_UPGRADER_API:
    urlpatterns += [
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
