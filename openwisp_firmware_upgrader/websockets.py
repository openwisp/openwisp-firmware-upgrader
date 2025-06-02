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
        self.publish_progress({
            "type": "log",
            "content": line,
            "status": status
        })

    def publish_status(self, status):
        self.publish_progress({
            "type": "status",
            "status": status
        })

    def publish_error(self, error_message):
        self.publish_progress({
            "type": "error",
            "message": error_message
        })


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
        self.publish_progress({
            "type": "operation_progress",
            "operation_id": operation_id,
            "status": status,
            "progress": progress
        })

    def publish_batch_status(self, status, completed, total):
        self.publish_progress({
            "type": "batch_status",
            "status": status,
            "completed": completed,
            "total": total
        })
