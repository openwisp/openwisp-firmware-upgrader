import os

import django
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

django.setup()

from channels.auth import AuthMiddlewareStack
from channels.security.websocket import AllowedHostsOriginValidator

from openwisp_controller.routing import get_routes
from openwisp_firmware_upgrader.routing import (
    get_routes as get_firmware_upgrader_routes,
)

application = ProtocolTypeRouter(
    {
        "http": get_asgi_application(),
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(
                URLRouter(get_routes() + get_firmware_upgrader_routes())
            )
        ),
    }
)
