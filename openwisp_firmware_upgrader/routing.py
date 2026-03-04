from django.urls import path

from .websockets import (
    BatchUpgradeProgressConsumer,
    DeviceUpgradeProgressConsumer,
    UpgradeProgressConsumer,
)

websocket_urlpatterns = [
    path(
        "ws/firmware-upgrader/upgrade-operation/<uuid:operation_id>/",
        UpgradeProgressConsumer.as_asgi(),
    ),
    path(
        "ws/firmware-upgrader/batch-upgrade-operation/<uuid:batch_id>/",
        BatchUpgradeProgressConsumer.as_asgi(),
    ),
    path(
        "ws/firmware-upgrader/device/<uuid:device_id>/",
        DeviceUpgradeProgressConsumer.as_asgi(),
    ),
]


def get_routes():
    return websocket_urlpatterns
