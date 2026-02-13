from django.urls import re_path

from .websockets import (
    BatchUpgradeProgressConsumer,
    DeviceUpgradeProgressConsumer,
    UpgradeProgressConsumer,
)

websocket_urlpatterns = [
    re_path(
        r"ws/firmware-upgrader/upgrade-operation/(?P<operation_id>[^/]+)/$",
        UpgradeProgressConsumer.as_asgi(),
    ),
    re_path(
        r"ws/firmware-upgrader/batch-upgrade-operation/(?P<batch_id>[^/]+)/$",
        BatchUpgradeProgressConsumer.as_asgi(),
    ),
    re_path(
        r"ws/firmware-upgrader/device/(?P<pk>[^/]+)/$",
        DeviceUpgradeProgressConsumer.as_asgi(),
    ),
]


def get_routes():
    return websocket_urlpatterns
