import asyncio
import json
import logging

from asgiref.sync import async_to_sync, sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.layers import get_channel_layer
from django.contrib.auth import get_permission_codename
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone
from swapper import load_model

logger = logging.getLogger(__name__)

# Module-level set to hold background task references
_background_tasks = set()


def _run_coroutine_safely(coro):
    """Execute ``coro`` regardless of whether an event loop is running.

    If there's an existing loop, schedule the coroutine as a background task and
    keep track of it so we can avoid warnings about unhandled tasks.  If no
    loop is running (i.e. we're in synchronous context), simply call it via
    ``async_to_sync``.
    """
    try:
        asyncio.get_running_loop()
        if asyncio.iscoroutine(coro):
            task = asyncio.create_task(coro)
        else:
            task = asyncio.create_task(coro())
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
    except RuntimeError:
        if asyncio.iscoroutine(coro):

            async def wrapper():
                await coro

            async_to_sync(wrapper)()
        else:
            async_to_sync(coro)()


class AuthenticatedWebSocketConsumer(AsyncJsonWebsocketConsumer):
    """
    Base websocket consumer with authentication and authorization methods.
    """

    @classmethod
    async def encode_json(cls, content):
        return json.dumps(content, cls=DjangoJSONEncoder)

    def _is_user_authenticated(self):
        try:
            user = self.scope["user"]
            return bool(getattr(user, "is_authenticated", False))
        except (KeyError, AttributeError):
            return False

    async def is_user_authorized(
        self,
        model=None,
        object_id=None,
        organization_field="organization_id",
    ):
        user = self.scope["user"]
        if user.is_superuser:
            return True
        return await sync_to_async(
            lambda: (
                user.is_staff
                and (
                    user.has_perm(
                        f"{model._meta.app_label}.{get_permission_codename('change', model._meta)}"
                    )
                    or user.has_perm(
                        f"{model._meta.app_label}.{get_permission_codename('view', model._meta)}"
                    )
                )
                and user.is_manager(
                    str(
                        model.objects.filter(pk=object_id)
                        .values_list(organization_field, flat=True)
                        .first()
                    )
                )
            )
        )()

    async def receive_json(self, content):
        """Handle incoming messages from the client"""
        message_type = content.get("type")
        if message_type != "request_current_state":
            logger.warning(f"Unknown message type received: {message_type}")
            return
        await self._handle_current_state_request(content)

    async def _handle_current_state_request(self, content):
        raise NotImplementedError(
            "Subclasses must implement _handle_current_state_request method"
        )

    async def disconnect(self, close_code):
        group = getattr(self, "group_name", "<missing>")
        channel = getattr(self, "channel_name", "<missing>")
        try:
            await self.channel_layer.group_discard(group, channel)
        except AttributeError:
            logger.exception(
                f"Attribute error when discarding channel {channel} from group {group}"
            )
            return


class UpgradeProgressConsumer(AuthenticatedWebSocketConsumer):
    """
    WebSocket consumer that streams progress updates for a single upgrade operation.
    """

    async def connect(self):
        try:
            auth_result = self._is_user_authenticated()
            if not auth_result:
                await self.close()
                return
            upgrade_operation_id = self.scope["url_route"]["kwargs"]["operation_id"]
            if not await self.is_user_authorized(
                model=load_model("firmware_upgrader", "UpgradeOperation"),
                object_id=upgrade_operation_id,
                organization_field="device__organization_id",
            ):
                await self.close()
                return
            self.operation_id = upgrade_operation_id
            self.group_name = f"upgrade_{self.operation_id}"
        except KeyError:
            logger.exception("Error in operation websocket connect")
            await self.close()
        else:
            try:
                await self.channel_layer.group_add(self.group_name, self.channel_name)
            except (ConnectionError, TimeoutError):
                logger.exception(f"Failed to add channel to group {self.group_name}")
                await self.close()
                return
            except RuntimeError:
                logger.exception(
                    f"Channel layer error when joining group {self.group_name}"
                )
                await self.close()
                return
            await self.accept()

    @sync_to_async
    def _get_upgrade_operation(self):
        UpgradeOperation = load_model("firmware_upgrader", "UpgradeOperation")
        return UpgradeOperation.objects.filter(pk=self.operation_id).first()

    async def _handle_current_state_request(self, content):
        """Handle request for current state of the operation"""
        # We import serializers here instead globally to prevent NotReady errors
        from .api.serializers import UpgradeOperationSerializer

        try:
            operation = await self._get_upgrade_operation()
            if not operation:
                return
            # Serialize operation using the existing serializer
            operation_data = await sync_to_async(
                lambda: UpgradeOperationSerializer(operation).data
            )()
            # Send operation update
            await self.send_json(
                {
                    "type": "operation_update",
                    "operation": operation_data,
                    "timestamp": timezone.now().isoformat(),
                }
            )
        except (ConnectionError, TimeoutError):
            logger.exception(
                "Failed to connect to channel layer during operation state request"
            )

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
                await self.close()
                return
            self.batch_id = self.scope["url_route"]["kwargs"]["batch_id"]
            if not await self.is_user_authorized(
                model=load_model("firmware_upgrader", "BatchUpgradeOperation"),
                object_id=self.batch_id,
                organization_field="build__category__organization_id",
            ):
                await self.close()
                return
            self.group_name = f"batch_upgrade_{self.batch_id}"
        except KeyError:
            logger.exception("Error in batch websocket connect")
            await self.close()
        else:
            try:
                await self.channel_layer.group_add(self.group_name, self.channel_name)
            except (ConnectionError, TimeoutError):
                logger.exception(f"Failed to add channel to group {self.group_name}")
                await self.close()
                return
            except RuntimeError:
                logger.exception(
                    f"Channel layer error when joining group {self.group_name}"
                )
                await self.close()
                return
            await self.accept()

    @sync_to_async
    def _get_batch_upgrade_operation(self):
        BatchUpgradeOperation = load_model("firmware_upgrader", "BatchUpgradeOperation")
        return BatchUpgradeOperation.objects.filter(pk=self.batch_id).first()

    async def _handle_current_state_request(self, content):
        """Handle request for current state of batch upgrade operations"""
        # We import serializers here instead globally to prevent NotReady errors.
        from .api.serializers import UpgradeOperationSerializer

        try:
            # Get the batch operation and its upgrade operations
            batch_operation = await self._get_batch_upgrade_operation()
            if batch_operation:
                # Get operations list
                operations_list = await sync_to_async(list)(
                    batch_operation.upgrade_operations.all()
                )
                # Serialize operations using the existing serializer
                operations_data = await sync_to_async(
                    lambda: UpgradeOperationSerializer(operations_list, many=True).data
                )()
                # Calculate counts
                total_operations = len(operations_list)
                completed_operations = sum(
                    1 for op in operations_list if op.status != "in-progress"
                )
                # Send everything in ONE message
                await self.send_json(
                    {
                        "type": "batch_state",
                        "batch_status": {
                            "status": batch_operation.status,
                            "completed": completed_operations,
                            "total": total_operations,
                        },
                        "operations": operations_data,
                    }
                )
        except (ConnectionError, TimeoutError):
            logger.exception(
                "Failed to connect to channel layer during batch state request"
            )
        except RuntimeError:
            logger.exception("Runtime error during batch state request")

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
                await self.close()
                return

            device_id = str(self.scope["url_route"]["kwargs"]["device_id"])
            if not await self.is_user_authorized(
                model=load_model("config", "Device"), object_id=device_id
            ):
                await self.close()
                return
            self.pk_ = device_id
            self.group_name = f"firmware_upgrader.device-{self.pk_}"
        except KeyError:
            logger.exception("Error in websocket connect")
            await self.close()
        else:
            try:
                await self.channel_layer.group_add(self.group_name, self.channel_name)
            except (ConnectionError, TimeoutError):
                logger.exception(f"Failed to add channel to group {self.group_name}")
                await self.close()
                return
            except RuntimeError:
                logger.exception(
                    f"Channel layer error when joining group {self.group_name}"
                )
                await self.close()
                return
            await self.accept()

    async def _handle_current_state_request(self, content):
        """Handle request for current state of in-progress operations"""
        from .api.serializers import DeviceUpgradeOperationSerializer

        UpgradeOperation = load_model("firmware_upgrader", "UpgradeOperation")
        try:
            # Get recent operations (including recently completed) for this device
            get_operations = sync_to_async(
                lambda: list(
                    UpgradeOperation.objects.filter(
                        device_id=self.pk_,
                        status__in=[
                            "in-progress",
                            "success",
                            "failed",
                            "aborted",
                            "cancelled",
                        ],
                    ).order_by("-modified")[:5]
                )
            )
            operations = await get_operations()
            # Serialize operations using the existing serializer
            operations_data = await sync_to_async(
                lambda: DeviceUpgradeOperationSerializer(operations, many=True).data
            )()
            # Send current state for each operation
            for operation_data in operations_data:
                await self.send_json(
                    {
                        "type": "operation_update",
                        "operation": operation_data,
                        "timestamp": timezone.now().isoformat(),
                    }
                )
        except (ConnectionError, TimeoutError):
            logger.exception(
                "Failed to connect to channel layer during current state request"
            )
        except RuntimeError:
            logger.exception("Runtime error during current state request")

    async def send_update(self, event):
        """Send upgrade progress updates to the device page"""
        await self.send_json(event["data"])


class UpgradeProgressPublisher:
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
            **data,
            "timestamp": timezone.now().isoformat(),
        }

        async def _send_messages():
            # Send to device-specific channel
            await self.channel_layer.group_send(
                self.device_group_name, {"type": "send_update", "data": message}
            )
            # Also send to operation-specific channel if available
            if hasattr(self, "operation_group_name"):
                await self.channel_layer.group_send(
                    self.operation_group_name,
                    {
                        "type": "upgrade_progress",
                        "data": message,
                    },
                )

        # schedule the coroutine safely (handles both sync and async callers)
        _run_coroutine_safely(_send_messages)

    def publish_operation_update(self, operation_data):
        """Publish complete operation update"""
        self.publish_progress({"type": "operation_update", "operation": operation_data})

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

        # Import serializer here to avoid circular imports and NotReady errors
        from .api.serializers import UpgradeOperationSerializer

        try:
            device_publisher = cls(instance.device.pk, instance.pk)
            device_publisher_data = UpgradeOperationSerializer(instance).data
            # DRF serializers does not convert ForeignKey fields to string,
            for field in ["device", "image"]:
                device_publisher_data[field] = str(device_publisher_data[field])
            device_publisher.publish_operation_update(device_publisher_data)
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
                batch_publisher.update_batch_status(instance.batch)
        except (ConnectionError, TimeoutError):
            logger.exception(
                f"Failed to connect to channel layer for upgrade operation {instance.pk}"
            )
        except RuntimeError:
            logger.exception(
                f"Runtime error in WebSocket publishing for upgrade operation {instance.pk}"
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
        async def _send_message():
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "batch_upgrade_progress",
                    "data": {**data, "timestamp": timezone.now().isoformat()},
                },
            )

        _run_coroutine_safely(_send_message)

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
        batch_status, stats = batch_instance.calculate_and_update_status()
        self.publish_batch_status(
            batch_status,
            stats["completed"],
            stats["total_operations"],
        )

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
        except (ConnectionError, TimeoutError):
            logger.exception(
                f"Failed to connect to channel layer for batch upgrade operation {instance.pk}"
            )
        except RuntimeError:
            logger.exception(
                f"Runtime error in WebSocket publishing for batch upgrade operation {instance.pk}"
            )
