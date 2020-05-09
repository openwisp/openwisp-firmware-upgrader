from django.urls import path
from openwisp_firmware_upgrader import settings as app_settings

from . import views

app_name = 'upgrader'

urlpatterns = []

if app_settings.FIRMWARE_UPGRADER_API:

    urlpatterns += [
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
