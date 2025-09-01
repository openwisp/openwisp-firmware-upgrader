import asyncio
import logging
from copy import deepcopy

from asgiref.sync import async_to_sync, sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.layers import get_channel_layer
from django.utils import timezone

logger = logging.getLogger(__name__)


def _convert_lazy_translations(obj):
    """Recursively convert Django lazy translation objects to strings for JSON serialization."""
    if isinstance(obj, dict):
        return {key: _convert_lazy_translations(value) for key, value in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return type(obj)(_convert_lazy_translations(item) for item in obj)
    elif hasattr(obj, "__str__") and hasattr(obj, "_proxy____cast"):
        return str(obj)
    else:
        return obj


class UpgradeProgressConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket consumer that streams progress updates for a single upgrade operation.
    """

    async def connect(self):
        self.operation_id = self.scope["url_route"]["kwargs"]["operation_id"]
        self.group_name = f"upgrade_{self.operation_id}"

        # Join room group
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def upgrade_progress(self, event):
        await self.send_json(event["data"])


class BatchUpgradeProgressConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket consumer that streams progress updates for a batch upgrade operation.
    """

    async def connect(self):
        self.batch_id = self.scope["url_route"]["kwargs"]["batch_id"]
        self.group_name = f"batch_upgrade_{self.batch_id}"

        # Join room group
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def batch_upgrade_progress(self, event):
        await self.send_json(event["data"])


class DeviceUpgradeProgressConsumer(AsyncJsonWebsocketConsumer):
    """
    Device-specific upgrade progress consumer for firmware upgrade progress
    """

    def _is_user_authenticated(self):
        try:
            assert self.scope["user"].is_authenticated is True
        except (KeyError, AssertionError):
            return False
        else:
            return True

    def is_user_authorized(self):
        user = self.scope["user"]
        is_authorized = user.is_superuser or user.is_staff
        return is_authorized

    async def connect(self):
        try:
            auth_result = self._is_user_authenticated()
            if not auth_result:
                return

            if not self.is_user_authorized():
                await self.close()
                return

            self.pk_ = self.scope["url_route"]["kwargs"]["pk"]
            self.group_name = f"firmware_upgrader.device-{self.pk_}"

        except (AssertionError, KeyError) as e:
            logger.error(f"Error in websocket connect: {e}")
            await self.close()
        else:
            try:
                await self.channel_layer.group_add(self.group_name, self.channel_name)
            except (ConnectionError, TimeoutError) as e:
                logger.error(f"Failed to add channel to group {self.group_name}: {e}")
                await self.close()
                return
            except RuntimeError as e:
                logger.error(
                    f"Channel layer error when joining group {self.group_name}: {e}"
                )
                await self.close()
                return

            await self.accept()

    async def disconnect(self, close_code):
        try:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        except AttributeError:
            return

    async def receive_json(self, content):
        """Handle incoming messages from the client"""
        message_type = content.get("type")

        if message_type == "request_current_state":
            await self._handle_current_state_request(content)
        else:
            logger.warning(f"Unknown message type received: {message_type}")

    async def _handle_current_state_request(self, content):
        """Handle request for current state of in-progress operations"""
        try:
            from .models import UpgradeOperation

            # Get recent operations (including recently completed) for this device using sync_to_async
            get_operations = sync_to_async(
                lambda: list(
                    UpgradeOperation.objects.filter(
                        device_id=self.pk_,
                        status__in=[
                            "in-progress",
                            "in progress",
                            "success",
                            "failed",
                            "aborted",
                        ],
                    )
                    .order_by("-modified")[:5]
                    .values("id", "status", "log", "progress", "modified", "created")
                )
            )

            operations = await get_operations()

            # Send current state for each in-progress operation
            for operation in operations:
                operation_data = {
                    "id": str(operation["id"]),
                    "status": operation["status"],
                    "log": operation["log"] or "",
                    "progress": operation.get("progress", 0),  # Include progress field
                    "modified": (
                        operation["modified"].isoformat()
                        if operation["modified"]
                        else None
                    ),
                    "created": (
                        operation["created"].isoformat()
                        if operation["created"]
                        else None
                    ),
                }

                # Send as operation update
                await self.send_json(
                    {
                        "model": "UpgradeOperation",
                        "data": {
                            "type": "operation_update",
                            "operation": operation_data,
                        },
                    }
                )
        except (ConnectionError, TimeoutError) as e:
            logger.error(
                f"Failed to connect to channel layer during current state request: {e}"
            )
        except RuntimeError as e:
            logger.error(f"Runtime error during current state request: {e}")

    async def send_update(self, event):
        """Send upgrade progress updates to the device page"""
        data = deepcopy(event)
        data.pop("type")
        await self.send_json(data)


class UpgradeProgressPublisher:
    """
    Helper to publish WebSocket messages for a single upgrade operation.
    """

    def __init__(self, operation_id):
        self.operation_id = operation_id
        self.channel_layer = get_channel_layer()
        self.group_name = f"upgrade_{operation_id}"

    def publish_progress(self, data):
        data = _convert_lazy_translations(data)

        async def _send_message():
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "upgrade_progress",
                    "data": {**data, "timestamp": timezone.now().isoformat()},
                },
            )

        async_to_sync(_send_message)()

    def publish_log(self, line, status):
        self.publish_progress({"type": "log", "content": line, "status": status})

    def publish_status(self, status):
        self.publish_progress({"type": "status", "status": status})

    def publish_error(self, error_message):
        self.publish_progress({"type": "error", "message": error_message})

    @classmethod
    def handle_upgrade_operation_log_updated(cls, sender, instance, line, **kwargs):
        """
        Handle log line events by publishing to WebSocket channels.
        """
        try:
            # Publish to operation-specific channel
            publisher = cls(instance.pk)
            publisher.publish_progress(
                {"type": "log", "content": line, "status": instance.status}
            )

            # Publish to device-specific channel for real-time UI updates
            device_publisher = DeviceUpgradeProgressPublisher(
                instance.device.pk, instance.pk
            )
            device_publisher.publish_log(line, instance.status)

        except (ConnectionError, TimeoutError) as e:
            logger.error(
                f"Failed to connect to channel layer for upgrade operation {instance.pk}: {e}",
                exc_info=True,
            )
        except RuntimeError as e:
            logger.error(
                f"Runtime error in WebSocket publishing for upgrade operation {instance.pk}: {e}",
                exc_info=True,
            )


class DeviceUpgradeProgressPublisher:
    """
    Publisher for device-specific upgrade progress that publishes to
    both individual operation channels and device channels
    """

    def __init__(self, device_id, operation_id=None):
        self.device_id = device_id
        self.operation_id = operation_id
        self.channel_layer = get_channel_layer()
        self.device_group_name = f"firmware_upgrader.device-{device_id}"
        if operation_id:
            self.operation_group_name = f"upgrade_{operation_id}"

    def publish_progress(self, data):
        """Publish to device-specific channel"""
        data = _convert_lazy_translations(data)

        message = {
            "type": "send_update",
            "model": "UpgradeOperation",
            "data": {**data, "timestamp": timezone.now().isoformat()},
        }

        async def _send_messages():
            # Send to device-specific channel
            await self.channel_layer.group_send(self.device_group_name, message)

            # Also send to operation-specific channel if available
            if hasattr(self, "operation_group_name"):
                await self.channel_layer.group_send(
                    self.operation_group_name,
                    {"type": "upgrade_progress", "data": data},
                )

        # Check if we're already in an async context
        try:
            asyncio.get_running_loop()
            asyncio.create_task(_send_messages())
        except RuntimeError:
            async_to_sync(_send_messages)()

    def publish_operation_update(self, operation_data):
        """Publish complete operation update"""
        self.publish_progress({"type": "operation_update", "operation": operation_data})

    def publish_log(self, line, status):
        self.publish_progress({"type": "log", "content": line, "status": status})

    def publish_status(self, status):
        self.publish_progress({"type": "status", "status": status})

    def publish_error(self, error_message):
        self.publish_progress({"type": "error", "message": error_message})

    @classmethod
    def handle_upgrade_operation_post_save(cls, sender, instance, created, **kwargs):
        """
        Handle UpgradeOperation post_save events by publishing status updates to WebSocket channels.
        """
        # Only publish updates for existing operations
        if created:
            return

        try:
            # Publish status update to operation-specific channel
            publisher = UpgradeProgressPublisher(instance.pk)
            publisher.publish_progress({"type": "status", "status": instance.status})

            # Publish complete operation update to device-specific channel
            device_publisher = cls(instance.device.pk, instance.pk)
            device_publisher.publish_operation_update(
                {
                    "id": str(instance.pk),
                    "device": str(instance.device.pk),
                    "status": instance.status,
                    "log": instance.log,
                    "progress": getattr(
                        instance, "progress", 0
                    ),  # Include progress field
                    "image": (
                        str(getattr(instance.image, "pk", None))
                        if getattr(instance.image, "pk", None)
                        else None
                    ),
                    "modified": (
                        instance.modified.isoformat() if instance.modified else None
                    ),
                    "created": (
                        instance.created.isoformat() if instance.created else None
                    ),
                }
            )
        except (ConnectionError, TimeoutError) as e:
            logger.error(
                f"Failed to connect to channel layer for upgrade operation {instance.pk}: {e}",
                exc_info=True,
            )
        except RuntimeError as e:
            logger.error(
                f"Runtime error in WebSocket publishing for upgrade operation {instance.pk}: {e}",
                exc_info=True,
            )


class BatchUpgradeProgressPublisher:
    """
    Helper to publish WebSocket messages for a batch upgrade operation.
    """

    def __init__(self, batch_id):
        self.batch_id = batch_id
        self.channel_layer = get_channel_layer()
        self.group_name = f"batch_upgrade_{batch_id}"

    def publish_progress(self, data):
        data = _convert_lazy_translations(data)

        async def _send_message():
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "batch_upgrade_progress",
                    "data": {**data, "timestamp": timezone.now().isoformat()},
                },
            )

        async_to_sync(_send_message)()

    def publish_operation_progress(self, operation_id, status, progress):
        self.publish_progress(
            {
                "type": "operation_progress",
                "operation_id": operation_id,
                "status": status,
                "progress": progress,
            }
        )

    def publish_batch_status(self, status, completed, total):
        self.publish_progress(
            {
                "type": "batch_status",
                "status": status,
                "completed": completed,
                "total": total,
            }
        )
