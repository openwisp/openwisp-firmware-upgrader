from django.urls import include, path

from . import views

app_name = 'upgrader'

urlpatterns = [
    path(
        'firmware-upgrader/',
        include(
            [
                path('build/', views.build_list, name='api_build_list'),
                path('build/<uuid:pk>/', views.build_detail, name='api_build_detail'),
                path(
                    'build/<uuid:pk>/upgrade/',
                    views.api_batch_upgrade,
                    name='api_build_batch_upgrade',
                ),
                path(
                    'build/<uuid:build_pk>/image/',
                    views.firmware_image_list,
                    name='api_firmware_list',
                ),
                path(
                    'build/<uuid:build_pk>/image/<uuid:pk>/',
                    views.firmware_image_detail,
                    name='api_firmware_detail',
                ),
                path(
                    'build/<uuid:build_pk>/image/<pk>/download/',
                    views.firmware_image_download,
                    name='api_firmware_download',
                ),
                path('category/', views.category_list, name='api_category_list'),
                path(
                    'category/<uuid:pk>/',
                    views.category_detail,
                    name='api_category_detail',
                ),
                path(
                    'batch-upgrade-operation/',
                    views.batch_upgrade_operation_list,
                    name='api_batchupgradeoperation_list',
                ),
                path(
                    'batch-upgrade-operation/<uuid:pk>/',
                    views.batch_upgrade_operation_detail,
                    name='api_batchupgradeoperation_detail',
                ),
                path(
                    'upgrade-operation/',
                    views.upgrade_operation_list,
                    name='api_upgradeoperation_list',
                ),
                path(
                    'upgrade-operation/<uuid:pk>/',
                    views.upgrade_operation_detail,
                    name='api_upgradeoperation_detail',
                ),
                path(
                    'device/<uuid:pk>/upgrade-operation/',
                    views.device_upgrade_operation_list,
                    name='api_deviceupgradeoperation_list',
                ),
                path(
                    'device/<uuid:pk>/firmware/',
                    views.device_firmware_detail,
                    name='api_devicefirmware_detail',
                ),
            ]
        ),
    ),
]
