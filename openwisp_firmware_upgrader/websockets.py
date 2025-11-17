import asyncio
import logging
from copy import deepcopy

from asgiref.sync import async_to_sync, sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.layers import get_channel_layer
from django.utils import timezone
from swapper import load_model

logger = logging.getLogger(__name__)


class AuthenticatedWebSocketConsumer(AsyncJsonWebsocketConsumer):
    """
    Base websocket consumer with authentication and authorization methods.
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


class UpgradeProgressConsumer(AuthenticatedWebSocketConsumer):
    """
    WebSocket consumer that streams progress updates for a single upgrade operation.
    """

    async def connect(self):
        try:
            auth_result = self._is_user_authenticated()
            if not auth_result:
                return

            if not self.is_user_authorized():
                await self.close()
                return

            self.operation_id = self.scope["url_route"]["kwargs"]["operation_id"]
            self.group_name = f"upgrade_{self.operation_id}"

        except (AssertionError, KeyError) as e:
            logger.error(f"Error in operation websocket connect: {e}")
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
            logger.error(
                f"Attribute error when discarding channel {self.channel_name} from group {self.group_name}"
            )
            return

    @sync_to_async
    def _get_upgrade_operation(self):
        UpgradeOperation = load_model("firmware_upgrader", "UpgradeOperation")
        return UpgradeOperation.objects.filter(pk=self.operation_id).first()

    async def receive_json(self, content):
        """Handle incoming messages from the client"""
        message_type = content.get("type")
        if not message_type:
            logger.warning("Received message without type")
            return
        await self._handle_current_operation_state_request(content)

    async def _handle_current_operation_state_request(self, content):
        """Handle request for current state of the operation"""
        try:
            operation = await self._get_upgrade_operation()
            if not operation:
                return
            # Send operation update
            await self.send_json(
                {
                    "type": "operation_update",
                    "operation": {
                        "id": str(operation.pk),
                        "status": operation.status,
                        "log": operation.log or "",
                        "progress": getattr(operation, "progress", 0),
                        "modified": (
                            operation.modified.isoformat()
                            if operation.modified
                            else None
                        ),
                    },
                }
            )
        except (ConnectionError, TimeoutError) as e:
            logger.error(
                f"Failed to connect to channel layer during operation state request: {e}"
            )
        except RuntimeError as e:
            logger.error(f"Runtime error during operation state request: {e}")

    async def upgrade_progress(self, event):
        await self.send_json(event["data"])


class BatchUpgradeProgressConsumer(AuthenticatedWebSocketConsumer):
    """
    WebSocket consumer that streams progress updates for a batch upgrade operation.
    """

    async def connect(self):
        try:
            auth_result = self._is_user_authenticated()
            if not auth_result:
                return
            if not self.is_user_authorized():
                await self.close()
                return
            self.batch_id = self.scope["url_route"]["kwargs"]["batch_id"]
            self.group_name = f"batch_upgrade_{self.batch_id}"

        except (AssertionError, KeyError) as e:
            logger.error(f"Error in batch websocket connect: {e}")
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
        if message_type != "request_current_state":
            logger.warning(f"Unknown message type received: {message_type}")
            return
        await self._handle_current_batch_state_request(content)

    @sync_to_async
    def _get_batch_upgrade_operation(self):
        BatchUpgradeOperation = load_model("firmware_upgrader", "BatchUpgradeOperation")
        return BatchUpgradeOperation.objects.filter(pk=self.batch_id).first()

    async def _handle_current_batch_state_request(self, content):
        """Handle request for current state of batch upgrade operations"""
        try:
            # Get the batch operation and its upgrade operations
            batch_operation = await self._get_batch_upgrade_operation()
            if batch_operation:
                # Send batch status
                total_operations = await sync_to_async(
                    batch_operation.upgrade_operations.count
                )()
                completed_operations = await sync_to_async(
                    batch_operation.upgrade_operations.exclude(
                        status="in-progress"
                    ).count
                )()
                await self.send_json(
                    {
                        "type": "batch_status",
                        "status": batch_operation.status,
                        "completed": completed_operations,
                        "total": total_operations,
                    }
                )
                # Send individual operation progress
                operations_list = await sync_to_async(list)(
                    batch_operation.upgrade_operations.all()
                )
                for operation in operations_list:
                    await self.send_json(
                        {
                            "type": "operation_progress",
                            "operation_id": str(operation.pk),
                            "status": operation.status,
                            "progress": getattr(operation, "progress", 0),
                            "modified": (
                                operation.modified.isoformat()
                                if operation.modified
                                else None
                            ),
                        }
                    )
        except (ConnectionError, TimeoutError) as e:
            logger.error(
                f"Failed to connect to channel layer during batch state request: {e}"
            )
        except RuntimeError as e:
            logger.error(f"Runtime error during batch state request: {e}")

    async def batch_upgrade_progress(self, event):
        await self.send_json(event["data"])


class DeviceUpgradeProgressConsumer(AuthenticatedWebSocketConsumer):
    """
    Device-specific upgrade progress consumer for firmware upgrade progress
    """

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
        UpgradeOperation = load_model("firmware_upgrader", "UpgradeOperation")
        try:
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
                            "cancelled",
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
        if created and not (hasattr(instance, "batch") and instance.batch):
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

            # Publish to batch upgrade channel if this operation belongs to a batch
            if hasattr(instance, "batch") and instance.batch:
                batch_publisher = BatchUpgradeProgressPublisher(instance.batch.pk)
                # Prepare device information
                device_info = {
                    "device_id": instance.device.pk,
                    "device_name": instance.device.name,
                    "image_name": str(instance.image) if instance.image else None,
                }
                batch_publisher.publish_operation_progress(
                    str(instance.pk),
                    instance.status,
                    getattr(instance, "progress", 0),
                    instance.modified,
                    device_info,
                )
                # Update batch status if needed
                batch_publisher.update_batch_status(instance.batch)
                if created:
                    batch_publisher.update_batch_status(instance.batch)
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

    def publish_operation_progress(
        self, operation_id, status, progress, modified=None, device_info=None
    ):
        progress_data = {
            "type": "operation_progress",
            "operation_id": operation_id,
            "status": status,
            "progress": progress,
            "modified": modified.isoformat() if modified else None,
        }
        # Add device information if available
        if device_info:
            progress_data.update(
                {
                    "device_id": str(device_info.get("device_id", "")),
                    "device_name": device_info.get("device_name", ""),
                    "image_name": device_info.get("image_name", ""),
                }
            )
        self.publish_progress(progress_data)

    def publish_batch_status(self, status, completed, total):
        self.publish_progress(
            {
                "type": "batch_status",
                "status": status,
                "completed": completed,
                "total": total,
            }
        )

    def update_batch_status(self, batch_instance):
        """Update and publish batch status based on current operations"""
        batch_instance.refresh_from_db()
        if hasattr(batch_instance, "_upgrade_operations"):
            delattr(batch_instance, "_upgrade_operations")
        operations = batch_instance.upgradeoperation_set
        total_operations = operations.count()
        in_progress_operations = operations.filter(status="in-progress").count()
        completed_operations = operations.exclude(status="in-progress").count()
        successful_operations = operations.filter(status="success").count()
        failed_operations = operations.filter(status="failed").count()
        cancelled_operations = operations.filter(status="cancelled").count()
        aborted_operations = operations.filter(status="aborted").count()

        # Determine overall batch status based on individual operation statuses
        if in_progress_operations > 0:
            batch_status = "in-progress"
        elif cancelled_operations > 0:
            batch_status = "cancelled"
        elif failed_operations > 0 or aborted_operations > 0:
            batch_status = "failed"
        elif (
            successful_operations > 0
            and completed_operations == total_operations
            and total_operations > 0
        ):
            batch_status = "success"
        else:
            batch_status = batch_instance.status

        if batch_instance.status != batch_status:
            batch_instance.status = batch_status
            batch_instance.save(update_fields=["status"])

        self.publish_batch_status(batch_status, completed_operations, total_operations)

    @classmethod
    def handle_batch_upgrade_operation_saved(cls, sender, instance, created, **kwargs):
        """
        Handle BatchUpgradeOperation post_save events by publishing status updates to WebSocket channels.
        """
        # Only publish updates for existing operations
        if created:
            return
        try:
            batch_publisher = cls(instance.pk)
            batch_publisher.update_batch_status(instance)
        except (ConnectionError, TimeoutError) as e:
            logger.error(
                f"Failed to connect to channel layer for batch upgrade operation {instance.pk}: {e}",
                exc_info=True,
            )
        except RuntimeError as e:
            logger.error(
                f"Runtime error in WebSocket publishing for batch upgrade operation {instance.pk}: {e}",
                exc_info=True,
            )
