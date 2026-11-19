from django.urls import include, path

from . import views

app_name = "upgrader"


def get_api_urls(api_views=views):
    """
    returns:: all the API urls of the firmware upgrader
    """

    def get_view(name):
        """Fall back to the standard view when a custom view is unavailable."""
        return getattr(api_views, name, getattr(views, name))

    return [
        path(
            "firmware-upgrader/",
            include(
                [
                    path("build/", get_view("build_list"), name="api_build_list"),
                    path(
                        "build/<uuid:pk>/",
                        get_view("build_detail"),
                        name="api_build_detail",
                    ),
                    path(
                        "build/<uuid:pk>/upgrade/",
                        get_view("api_batch_upgrade"),
                        name="api_build_batch_upgrade",
                    ),
                    path(
                        "build/<uuid:build_pk>/image/",
                        get_view("firmware_image_list"),
                        name="api_firmware_list",
                    ),
                    path(
                        "build/<uuid:build_pk>/image/<uuid:pk>/",
                        get_view("firmware_image_detail"),
                        name="api_firmware_detail",
                    ),
                    path(
                        "build/<uuid:build_pk>/image/<pk>/download/",
                        get_view("firmware_image_download"),
                        name="api_firmware_download",
                    ),
                    path(
                        "category/", get_view("category_list"), name="api_category_list"
                    ),
                    path(
                        "category/<uuid:pk>/",
                        get_view("category_detail"),
                        name="api_category_detail",
                    ),
                    path(
                        "batch-upgrade-operation/",
                        get_view("batch_upgrade_operation_list"),
                        name="api_batchupgradeoperation_list",
                    ),
                    path(
                        "batch-upgrade-operation/<uuid:pk>/",
                        get_view("batch_upgrade_operation_detail"),
                        name="api_batchupgradeoperation_detail",
                    ),
                    path(
                        "upgrade-operation/",
                        get_view("upgrade_operation_list"),
                        name="api_upgradeoperation_list",
                    ),
                    path(
                        "upgrade-operation/<uuid:pk>/",
                        get_view("upgrade_operation_detail"),
                        name="api_upgradeoperation_detail",
                    ),
                    path(
                        "upgrade-operation/<uuid:pk>/cancel/",
                        get_view("upgrade_operation_cancel"),
                        name="api_upgradeoperation_cancel",
                    ),
                    path(
                        "device/<uuid:pk>/upgrade-operation/",
                        get_view("device_upgrade_operation_list"),
                        name="api_deviceupgradeoperation_list",
                    ),
                    path(
                        "device/<uuid:pk>/firmware/",
                        get_view("device_firmware_detail"),
                        name="api_devicefirmware_detail",
                    ),
                ]
            ),
        ),
    ]


urlpatterns = get_api_urls()
