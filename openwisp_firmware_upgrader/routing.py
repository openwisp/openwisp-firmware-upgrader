from django.urls import re_path
from .websockets import UpgradeProgressConsumer, BatchUpgradeProgressConsumer

websocket_urlpatterns = [
    re_path(
        r"ws/upgrade/(?P<operation_id>[^/]+)/$",
        UpgradeProgressConsumer.as_asgi(),
    ),
    re_path(
        r"ws/batch-upgrade/(?P<batch_id>[^/]+)/$",
        BatchUpgradeProgressConsumer.as_asgi(),
    ),
]
