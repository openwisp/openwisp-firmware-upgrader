from copy import deepcopy

from asgiref.sync import async_to_sync
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.layers import get_channel_layer
from django.utils import timezone


class UpgradeProgressConsumer(AsyncJsonWebsocketConsumer):
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
            self.close()
            return False
        else:
            return True

    def is_user_authorized(self):
        user = self.scope["user"]
        return user.is_superuser or user.is_staff

    async def connect(self):
        try:
            assert self._is_user_authenticated() and self.is_user_authorized()
            self.pk_ = self.scope["url_route"]["kwargs"]["pk"]
            self.group_name = f"firmware_upgrader.device-{self.pk_}"
        except (AssertionError, KeyError):
            await self.close()
        else:
            await self.channel_layer.group_add(self.group_name, self.channel_name)
            await self.accept()

    async def disconnect(self, close_code):
        try:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        except AttributeError:
            return

    async def send_update(self, event):
        """Send upgrade progress updates to the device page"""
        data = deepcopy(event)
        data.pop("type")
        await self.send_json(data)


class UpgradeProgressPublisher:
    def __init__(self, operation_id):
        self.operation_id = operation_id
        self.channel_layer = get_channel_layer()
        self.group_name = f"upgrade_{operation_id}"

    def publish_progress(self, data):
        async_to_sync(self.channel_layer.group_send)(
            self.group_name,
            {
                "type": "upgrade_progress",
                "data": {**data, "timestamp": timezone.now().isoformat()},
            },
        )

    def publish_log(self, line, status):
        self.publish_progress({"type": "log", "content": line, "status": status})

    def publish_status(self, status):
        self.publish_progress({"type": "status", "status": status})

    def publish_error(self, error_message):
        self.publish_progress({"type": "error", "message": error_message})


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
        message = {
            "type": "send_update",
            "model": "UpgradeOperation",
            "data": {**data, "timestamp": timezone.now().isoformat()},
        }

        # Send to device-specific channel
        async_to_sync(self.channel_layer.group_send)(self.device_group_name, message)

        # Also send to operation-specific channel if available
        if hasattr(self, "operation_group_name"):
            async_to_sync(self.channel_layer.group_send)(
                self.operation_group_name, {"type": "upgrade_progress", "data": data}
            )

    def publish_operation_update(self, operation_data):
        """Publish complete operation update"""
        self.publish_progress({"type": "operation_update", "operation": operation_data})

    def publish_log(self, line, status):
        self.publish_progress({"type": "log", "content": line, "status": status})

    def publish_status(self, status):
        self.publish_progress({"type": "status", "status": status})

    def publish_error(self, error_message):
        self.publish_progress({"type": "error", "message": error_message})


class BatchUpgradeProgressPublisher:
    def __init__(self, batch_id):
        self.batch_id = batch_id
        self.channel_layer = get_channel_layer()
        self.group_name = f"batch_upgrade_{batch_id}"

    def publish_progress(self, data):
        async_to_sync(self.channel_layer.group_send)(
            self.group_name,
            {
                "type": "batch_upgrade_progress",
                "data": {**data, "timestamp": timezone.now().isoformat()},
            },
        )

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
