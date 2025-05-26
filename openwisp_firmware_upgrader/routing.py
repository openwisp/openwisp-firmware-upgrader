from django.urls import re_path

from . import websockets

websocket_urlpatterns = [
    re_path(
        r'ws/upgrade/(?P<operation_id>[^/]+)/$',
        websockets.UpgradeProgressConsumer.as_asgi(),
    ),
]
