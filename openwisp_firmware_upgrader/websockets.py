from copy import deepcopy
import logging

from asgiref.sync import async_to_sync, sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.layers import get_channel_layer
from django.utils import timezone

logger = logging.getLogger(__name__)


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
            user = self.scope.get("user")
            logger.debug(f"WebSocket authentication check - User: {user}, Authenticated: {getattr(user, 'is_authenticated', False)}")
            assert self.scope["user"].is_authenticated is True
        except (KeyError, AssertionError) as e:
            logger.warning(f"WebSocket authentication failed: {e}")
            return False
        else:
            logger.debug("WebSocket authentication successful")
            return True

    def is_user_authorized(self):
        user = self.scope["user"]
        is_authorized = user.is_superuser or user.is_staff
        logger.debug(f"WebSocket authorization check - User: {user.username if hasattr(user, 'username') else 'Unknown'}, Superuser: {getattr(user, 'is_superuser', False)}, Staff: {getattr(user, 'is_staff', False)}, Authorized: {is_authorized}")
        return is_authorized

    async def connect(self):
        logger.info(f"🟢 WebSocket connection attempt from {self.scope.get('client', 'unknown')}")
        print(f"🟢 WebSocket connection attempt from {self.scope.get('client', 'unknown')}")
        
        try:
            auth_result = self._is_user_authenticated()
            if not auth_result:
                logger.warning("🔴 WebSocket connection rejected due to authentication failure")
                print("🔴 WebSocket connection rejected due to authentication failure")
                return
                
            if not self.is_user_authorized():
                logger.warning("🔴 WebSocket connection rejected due to authorization failure") 
                print("🔴 WebSocket connection rejected due to authorization failure")
                await self.close()
                return
                
            self.pk_ = self.scope["url_route"]["kwargs"]["pk"]
            self.group_name = f"firmware_upgrader.device-{self.pk_}"
            logger.info(f"🟡 WebSocket connecting to group: {self.group_name}")
            print(f"🟡 WebSocket connecting to group: {self.group_name}")
            
        except (AssertionError, KeyError) as e:
            logger.error(f"🔴 WebSocket connection failed with error: {e}")
            print(f"🔴 WebSocket connection failed with error: {e}")
            await self.close()
        else:
            logger.info(f"🔧 About to join group: {self.group_name}, channel: {self.channel_name}")
            print(f"🔧 About to join group: {self.group_name}, channel: {self.channel_name}")
            
            try:
                await self.channel_layer.group_add(self.group_name, self.channel_name)
                logger.info(f"🔧 Group add COMPLETED successfully")
                print(f"🔧 Group add COMPLETED successfully")
            except Exception as e:
                logger.error(f"🔧 Group add FAILED: {e}")
                print(f"🔧 Group add FAILED: {e}")
                await self.close()
                return
                
            await self.accept()
            logger.info(f"✅ WebSocket connection FULLY ESTABLISHED for device {self.pk_}, channel: {self.channel_name}")
            print(f"✅ WebSocket connection FULLY ESTABLISHED for device {self.pk_}, channel: {self.channel_name}")
            
            # Test if consumer stays alive by logging every 5 seconds
            import asyncio
            asyncio.create_task(self._heartbeat())

    async def _heartbeat(self):
        """Log heartbeat to track if consumer stays alive"""
        import asyncio
        while True:
            try:
                await asyncio.sleep(5)
                logger.info(f"💓 Consumer ALIVE for device {self.pk_}")
                print(f"💓 Consumer ALIVE for device {self.pk_}")
            except Exception:
                break

    async def disconnect(self, close_code):
        logger.info(f"🔴 WebSocket disconnecting with code: {close_code}")
        print(f"🔴 WebSocket disconnecting with code: {close_code}")
        try:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
            logger.info(f"🔴 WebSocket removed from group: {self.group_name}")
            print(f"🔴 WebSocket removed from group: {self.group_name}")
        except AttributeError:
            logger.warning("🔴 WebSocket disconnect: group_name not found")
            print("🔴 WebSocket disconnect: group_name not found")
            return

    async def receive_json(self, content):
        """Handle incoming messages from the client"""
        message_type = content.get('type')
        
        if message_type == 'request_current_state':
            await self._handle_current_state_request(content)
        else:
            logger.warning(f"Unknown message type received: {message_type}")

    async def _handle_current_state_request(self, content):
        """Handle request for current state of in-progress operations"""
        try:
            # Import here to avoid circular imports
            from .models import UpgradeOperation
            
            # Get in-progress operations for this device using sync_to_async
            get_operations = sync_to_async(
                lambda: list(UpgradeOperation.objects.filter(
                    device_id=self.pk_,
                    status__in=['in-progress', 'in progress']
                ).values(
                    'id', 'status', 'log', 'modified', 'created'
                ))
            )
            
            operations = await get_operations()
            
            # Send current state for each in-progress operation
            for operation in operations:
                operation_data = {
                    'id': str(operation['id']),
                    'status': operation['status'],
                    'log': operation['log'] or '',
                    'modified': operation['modified'].isoformat() if operation['modified'] else None,
                    'created': operation['created'].isoformat() if operation['created'] else None,
                }
                
                # Send as operation update
                await self.send_json({
                    'model': 'UpgradeOperation',
                    'data': {
                        'type': 'operation_update',
                        'operation': operation_data
                    }
                })
                
                logger.info(f"📤 Sent current state for operation {operation['id']}")
                
        except Exception as e:
            logger.error(f"Error handling current state request: {e}")

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
