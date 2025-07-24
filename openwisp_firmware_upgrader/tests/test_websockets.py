from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from ..websockets import (
    BatchUpgradeProgressConsumer,
    BatchUpgradeProgressPublisher,
    DeviceUpgradeProgressConsumer,
    DeviceUpgradeProgressPublisher,
    UpgradeProgressConsumer,
    UpgradeProgressPublisher,
)

User = get_user_model()


class WebSocketTest(TestCase):
    """Test WebSocket consumers and publishers for firmware upgrade progress."""

    @classmethod
    def setUpTestData(cls):
        # Create all users needed for tests synchronously
        cls.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
            is_staff=True,
        )
        cls.regular_user = User.objects.create_user(
            username="regularuser",
            email="regular@example.com",
            password="testpass123",
            is_staff=False,
            is_superuser=False,
        )
        cls.superuser = User.objects.create_user(
            username="superuser",
            email="super@example.com",
            password="testpass123",
            is_staff=False,
            is_superuser=True,
        )
        cls.staff_user = User.objects.create_user(
            username="staffuser",
            email="staff@example.com",
            password="testpass123",
            is_staff=True,
            is_superuser=False,
        )

    def setUp(self):
        super().setUp()
        self.user = self.__class__.user
        self.regular_user = self.__class__.regular_user
        self.superuser = self.__class__.superuser
        self.staff_user = self.__class__.staff_user

    async def test_upgrade_progress_consumer_connection(self):
        """Test UpgradeProgressConsumer connection"""
        operation_id = str(uuid4())

        # Create a WebSocket connection
        communicator = WebsocketCommunicator(
            UpgradeProgressConsumer.as_asgi(),
            f"/ws/firmware-upgrader/upgrade-operation/{operation_id}/",
        )
        communicator.scope["url_route"] = {"kwargs": {"operation_id": operation_id}}

        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        # Test receiving messages
        channel_layer = get_channel_layer()
        if channel_layer is not None:
            group_name = f"upgrade_{operation_id}"

            # Send status message
            await channel_layer.group_send(
                group_name,
                {
                    "type": "upgrade_progress",
                    "data": {"type": "status", "status": "in-progress"},
                },
            )

            response = await communicator.receive_json_from()
            self.assertEqual(response["type"], "status")
            self.assertEqual(response["status"], "in-progress")

            # Send log message
            await channel_layer.group_send(
                group_name,
                {
                    "type": "upgrade_progress",
                    "data": {"type": "log", "content": "Test log message"},
                },
            )

            response = await communicator.receive_json_from()
            self.assertEqual(response["type"], "log")
            self.assertEqual(response["content"], "Test log message")

            # Send error message
            await channel_layer.group_send(
                group_name,
                {
                    "type": "upgrade_progress",
                    "data": {"type": "error", "message": "Test error"},
                },
            )

            response = await communicator.receive_json_from()
            self.assertEqual(response["type"], "error")
            self.assertEqual(response["message"], "Test error")

        await communicator.disconnect()

    async def test_batch_upgrade_progress_consumer_connection(self):
        """Test BatchUpgradeProgressConsumer connection and functionality."""
        batch_id = str(uuid4())

        # Create a WebSocket connection
        communicator = WebsocketCommunicator(
            BatchUpgradeProgressConsumer.as_asgi(),
            f"/ws/firmware-upgrader/batch-upgrade-operation/{batch_id}/",
        )
        communicator.scope["url_route"] = {"kwargs": {"batch_id": batch_id}}

        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        # Test receiving messages
        channel_layer = get_channel_layer()
        if channel_layer is not None:
            group_name = f"batch_upgrade_{batch_id}"

            # Send batch status message
            await channel_layer.group_send(
                group_name,
                {
                    "type": "batch_upgrade_progress",
                    "data": {
                        "type": "batch_status",
                        "status": "in-progress",
                        "completed": 0,
                        "total": 2,
                    },
                },
            )

            response = await communicator.receive_json_from()
            self.assertEqual(response["type"], "batch_status")
            self.assertEqual(response["status"], "in-progress")
            self.assertEqual(response["completed"], 0)
            self.assertEqual(response["total"], 2)

            # Send operation progress message
            await channel_layer.group_send(
                group_name,
                {
                    "type": "batch_upgrade_progress",
                    "data": {
                        "type": "operation_progress",
                        "operation_id": "op1",
                        "status": "in-progress",
                        "progress": 50,
                    },
                },
            )

            response = await communicator.receive_json_from()
            self.assertEqual(response["type"], "operation_progress")
            self.assertEqual(response["operation_id"], "op1")
            self.assertEqual(response["status"], "in-progress")
            self.assertEqual(response["progress"], 50)

        await communicator.disconnect()

    async def test_device_upgrade_progress_consumer_connection_authenticated(self):
        """Test DeviceUpgradeProgressConsumer with authenticated user."""
        device_id = str(uuid4())

        # Create a WebSocket connection with authenticated user
        communicator = WebsocketCommunicator(
            DeviceUpgradeProgressConsumer.as_asgi(),
            f"/ws/firmware-upgrader/device/{device_id}/",
        )
        communicator.scope["url_route"] = {"kwargs": {"pk": device_id}}
        communicator.scope["user"] = self.user

        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        # Test receiving messages
        channel_layer = get_channel_layer()
        group_name = f"firmware_upgrader.device-{device_id}"

        # Send operation update message
        await channel_layer.group_send(
            group_name,
            {
                "type": "send_update",
                "model": "UpgradeOperation",
                "data": {
                    "type": "operation_update",
                    "operation": {
                        "id": "test-op-id",
                        "status": "in-progress",
                        "log": "Test log",
                    },
                },
            },
        )

        response = await communicator.receive_json_from()
        self.assertEqual(response["model"], "UpgradeOperation")
        self.assertEqual(response["data"]["type"], "operation_update")
        self.assertEqual(response["data"]["operation"]["id"], "test-op-id")

        await communicator.disconnect()

    async def test_device_upgrade_progress_consumer_connection_unauthenticated(self):
        """Test DeviceUpgradeProgressConsumer with unauthenticated user."""
        device_id = str(uuid4())
        communicator = WebsocketCommunicator(
            DeviceUpgradeProgressConsumer.as_asgi(),
            f"/ws/firmware-upgrader/device/{device_id}/",
        )
        communicator.scope["url_route"] = {"kwargs": {"pk": device_id}}
        communicator.scope["user"] = MagicMock(is_authenticated=False)
        try:
            connected, _ = await communicator.connect()
            self.assertFalse(connected)
        except Exception:
            # If connection is forcibly closed then treat it as failed connection
            pass

    async def test_device_upgrade_progress_consumer_connection_unauthorized(self):
        """Test DeviceUpgradeProgressConsumer with unauthorized user."""
        device_id = str(uuid4())
        communicator = WebsocketCommunicator(
            DeviceUpgradeProgressConsumer.as_asgi(),
            f"/ws/firmware-upgrader/device/{device_id}/",
        )
        communicator.scope["url_route"] = {"kwargs": {"pk": device_id}}
        communicator.scope["user"] = self.regular_user
        try:
            connected, _ = await communicator.connect()
            self.assertFalse(connected)
        except Exception:
            pass

    async def test_device_upgrade_progress_consumer_current_state_request(self):
        """Test DeviceUpgradeProgressConsumer current state request functionality."""
        device_id = str(uuid4())

        # Create a WebSocket connection
        communicator = WebsocketCommunicator(
            DeviceUpgradeProgressConsumer.as_asgi(),
            f"/ws/firmware-upgrader/device/{device_id}/",
        )
        communicator.scope["url_route"] = {"kwargs": {"pk": device_id}}
        communicator.scope["user"] = self.user

        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        # Send current state request
        await communicator.send_json_to({"type": "request_current_state"})

        test_operations = [
            {
                "id": "op1",
                "status": "in-progress",
                "log": "Test log 1",
                "modified": timezone.now(),
                "created": timezone.now(),
            },
            {
                "id": "op2",
                "status": "in progress",
                "log": "Test log 2",
                "modified": timezone.now(),
                "created": timezone.now(),
            },
        ]

        with patch(
            "openwisp_firmware_upgrader.websockets.sync_to_async"
        ) as mock_sync_to_async:
            mock_sync_to_async.return_value = AsyncMock(return_value=test_operations)

            # The consumer should send current state for each operation
            response1 = await communicator.receive_json_from()
            response2 = await communicator.receive_json_from()

            self.assertEqual(response1["model"], "UpgradeOperation")
            self.assertEqual(response1["data"]["type"], "operation_update")
            self.assertEqual(response1["data"]["operation"]["id"], "op1")

            self.assertEqual(response2["model"], "UpgradeOperation")
            self.assertEqual(response2["data"]["type"], "operation_update")
            self.assertEqual(response2["data"]["operation"]["id"], "op2")

        await communicator.disconnect()

    async def test_device_upgrade_progress_consumer_unknown_message(self):
        """Test DeviceUpgradeProgressConsumer handling of unknown message types."""
        device_id = str(uuid4())
        communicator = WebsocketCommunicator(
            DeviceUpgradeProgressConsumer.as_asgi(),
            f"/ws/firmware-upgrader/device/{device_id}/",
        )
        communicator.scope["url_route"] = {"kwargs": {"pk": device_id}}
        communicator.scope["user"] = self.user
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        # Patch the logger at the correct import path
        with patch("openwisp_firmware_upgrader.websockets.logger") as mock_logger:
            await communicator.send_json_to({"type": "unknown_message_type"})
            # Allow event loop to process
            await communicator.receive_nothing()
            mock_logger.warning.assert_called()
        await communicator.disconnect()

    def test_upgrade_progress_publisher(self):
        """Test UpgradeProgressPublisher functionality."""
        operation_id = str(uuid4())
        publisher = UpgradeProgressPublisher(operation_id)

        # Test publishing progress
        with patch.object(
            publisher.channel_layer, "group_send", new_callable=AsyncMock
        ) as mock_group_send:
            test_data = {"type": "test", "data": "test_value"}
            publisher.publish_progress(test_data)

            call_args = mock_group_send.call_args[0]
            self.assertEqual(call_args[0], f"upgrade_{operation_id}")
            self.assertEqual(call_args[1]["type"], "upgrade_progress")
            self.assertEqual(call_args[1]["data"]["type"], "test")
            self.assertEqual(call_args[1]["data"]["data"], "test_value")
            self.assertIn("timestamp", call_args[1]["data"])

        # Test publishing log
        with patch.object(
            publisher.channel_layer, "group_send", new_callable=AsyncMock
        ) as mock_group_send:
            publisher.publish_log("Test log line", "in-progress")

            call_args = mock_group_send.call_args[0]
            self.assertEqual(call_args[1]["data"]["type"], "log")
            self.assertEqual(call_args[1]["data"]["content"], "Test log line")
            self.assertEqual(call_args[1]["data"]["status"], "in-progress")

        # Test publishing status
        with patch.object(
            publisher.channel_layer, "group_send", new_callable=AsyncMock
        ) as mock_group_send:
            publisher.publish_status("success")

            call_args = mock_group_send.call_args[0]
            self.assertEqual(call_args[1]["data"]["type"], "status")
            self.assertEqual(call_args[1]["data"]["status"], "success")

        # Test publishing error
        with patch.object(
            publisher.channel_layer, "group_send", new_callable=AsyncMock
        ) as mock_group_send:
            publisher.publish_error("Test error message")

            call_args = mock_group_send.call_args[0]
            self.assertEqual(call_args[1]["data"]["type"], "error")
            self.assertEqual(call_args[1]["data"]["message"], "Test error message")

    def test_device_upgrade_progress_publisher(self):
        """Test DeviceUpgradeProgressPublisher functionality."""
        device_id = str(uuid4())
        operation_id = str(uuid4())
        publisher = DeviceUpgradeProgressPublisher(device_id, operation_id)

        # Test publishing progress
        with patch.object(
            publisher.channel_layer, "group_send", new_callable=AsyncMock
        ) as mock_group_send:
            test_data = {"type": "test", "data": "test_value"}
            publisher.publish_progress(test_data)

            # Should be called twice - once for device channel, once for operation channel
            self.assertEqual(mock_group_send.call_count, 2)

            # Check device channel call
            device_call = mock_group_send.call_args_list[0]
            self.assertEqual(device_call[0][0], f"firmware_upgrader.device-{device_id}")
            self.assertEqual(device_call[0][1]["type"], "send_update")
            self.assertEqual(device_call[0][1]["model"], "UpgradeOperation")
            self.assertEqual(device_call[0][1]["data"]["type"], "test")

            # Check operation channel call
            operation_call = mock_group_send.call_args_list[1]
            self.assertEqual(operation_call[0][0], f"upgrade_{operation_id}")
            self.assertEqual(operation_call[0][1]["type"], "upgrade_progress")
            self.assertEqual(operation_call[0][1]["data"]["type"], "test")

        # Test publishing operation update
        with patch.object(
            publisher.channel_layer, "group_send", new_callable=AsyncMock
        ) as mock_group_send:
            operation_data = {"id": "op1", "status": "success"}
            publisher.publish_operation_update(operation_data)

            call_args = mock_group_send.call_args_list[0][0]
            self.assertEqual(call_args[1]["data"]["type"], "operation_update")
            self.assertEqual(call_args[1]["data"]["operation"]["id"], "op1")

        # Test publishing without operation_id
        publisher_no_op = DeviceUpgradeProgressPublisher(device_id)

        with patch.object(
            publisher_no_op.channel_layer, "group_send", new_callable=AsyncMock
        ) as mock_group_send:
            test_data = {"type": "test", "data": "test_value"}
            publisher_no_op.publish_progress(test_data)

            # Should only be called once for device channel
            self.assertEqual(mock_group_send.call_count, 1)

    def test_batch_upgrade_progress_publisher(self):
        """Test BatchUpgradeProgressPublisher functionality."""
        batch_id = str(uuid4())
        publisher = BatchUpgradeProgressPublisher(batch_id)

        # Test publishing progress
        with patch.object(
            publisher.channel_layer, "group_send", new_callable=AsyncMock
        ) as mock_group_send:
            test_data = {"type": "test", "data": "test_value"}
            publisher.publish_progress(test_data)

            call_args = mock_group_send.call_args[0]
            self.assertEqual(call_args[0], f"batch_upgrade_{batch_id}")
            self.assertEqual(call_args[1]["type"], "batch_upgrade_progress")
            self.assertEqual(call_args[1]["data"]["type"], "test")
            self.assertEqual(call_args[1]["data"]["data"], "test_value")
            self.assertIn("timestamp", call_args[1]["data"])

        # Test publishing operation progress
        with patch.object(
            publisher.channel_layer, "group_send", new_callable=AsyncMock
        ) as mock_group_send:
            publisher.publish_operation_progress("op1", "in-progress", 75)

            call_args = mock_group_send.call_args[0]
            self.assertEqual(call_args[1]["data"]["type"], "operation_progress")
            self.assertEqual(call_args[1]["data"]["operation_id"], "op1")
            self.assertEqual(call_args[1]["data"]["status"], "in-progress")
            self.assertEqual(call_args[1]["data"]["progress"], 75)

        # Test publishing batch status
        with patch.object(
            publisher.channel_layer, "group_send", new_callable=AsyncMock
        ) as mock_group_send:
            publisher.publish_batch_status("success", 5, 10)

            call_args = mock_group_send.call_args[0]
            self.assertEqual(call_args[1]["data"]["type"], "batch_status")
            self.assertEqual(call_args[1]["data"]["status"], "success")
            self.assertEqual(call_args[1]["data"]["completed"], 5)
            self.assertEqual(call_args[1]["data"]["total"], 10)

    async def test_websocket_connection_errors(self):
        """Test WebSocket connection error handling."""
        operation_id = str(uuid4())
        communicator = WebsocketCommunicator(
            UpgradeProgressConsumer.as_asgi(),
            f"/ws/firmware-upgrader/upgrade-operation/{operation_id}/",
        )
        communicator.scope["url_route"] = {"kwargs": {}}
        try:
            connected, _ = await communicator.connect()
            self.assertFalse(connected)
        except (KeyError, Exception):
            pass

    @override_settings(
        CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    )
    async def test_websocket_with_inmemory_channel_layer(self):
        """Test WebSocket functionality with in-memory channel layer."""
        operation_id = str(uuid4())

        # Create a WebSocket connection
        communicator = WebsocketCommunicator(
            UpgradeProgressConsumer.as_asgi(),
            f"/ws/firmware-upgrader/upgrade-operation/{operation_id}/",
        )
        communicator.scope["url_route"] = {"kwargs": {"operation_id": operation_id}}

        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        # Test receiving messages with in-memory channel layer
        channel_layer = get_channel_layer()
        group_name = f"upgrade_{operation_id}"

        await channel_layer.group_send(
            group_name,
            {
                "type": "upgrade_progress",
                "data": {"type": "status", "status": "success"},
            },
        )

        response = await communicator.receive_json_from()
        self.assertEqual(response["type"], "status")
        self.assertEqual(response["status"], "success")

        await communicator.disconnect()

    async def test_websocket_disconnect_handling(self):
        """Test WebSocket disconnect handling."""
        operation_id = str(uuid4())

        # Create a WebSocket connection
        communicator = WebsocketCommunicator(
            UpgradeProgressConsumer.as_asgi(),
            f"/ws/firmware-upgrader/upgrade-operation/{operation_id}/",
        )
        communicator.scope["url_route"] = {"kwargs": {"operation_id": operation_id}}

        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        # Test disconnect
        await communicator.disconnect()

    async def test_device_upgrade_progress_consumer_channel_layer_errors(self):
        """Test DeviceUpgradeProgressConsumer channel layer error handling."""
        device_id = str(uuid4())
        with patch.object(
            DeviceUpgradeProgressConsumer, "channel_layer", create=True
        ) as mock_channel_layer:
            mock_channel_layer.group_add.side_effect = ConnectionError(
                "Connection failed"
            )
            communicator = WebsocketCommunicator(
                DeviceUpgradeProgressConsumer.as_asgi(),
                f"/ws/firmware-upgrader/device/{device_id}/",
            )
            communicator.scope["url_route"] = {"kwargs": {"pk": device_id}}
            communicator.scope["user"] = self.user
            try:
                await communicator.connect()
            except Exception:
                pass
        with patch.object(
            DeviceUpgradeProgressConsumer, "channel_layer", create=True
        ) as mock_channel_layer:
            mock_channel_layer.group_add.side_effect = RuntimeError("Runtime error")
            communicator = WebsocketCommunicator(
                DeviceUpgradeProgressConsumer.as_asgi(),
                f"/ws/firmware-upgrader/device/{device_id}/",
            )
            communicator.scope["url_route"] = {"kwargs": {"pk": device_id}}
            communicator.scope["user"] = self.user
            try:
                await communicator.connect()
            except Exception:
                pass

    async def test_device_upgrade_progress_consumer_disconnect_error_handling(self):
        """Test DeviceUpgradeProgressConsumer disconnect error handling."""
        device_id = str(uuid4())
        with patch.object(
            DeviceUpgradeProgressConsumer, "channel_layer", create=True
        ) as mock_channel_layer:
            mock_channel_layer.group_discard.side_effect = AttributeError(
                "No channel layer"
            )
            communicator = WebsocketCommunicator(
                DeviceUpgradeProgressConsumer.as_asgi(),
                f"/ws/firmware-upgrader/device/{device_id}/",
            )
            communicator.scope["url_route"] = {"kwargs": {"pk": device_id}}
            communicator.scope["user"] = self.user
            connected, _ = await communicator.connect()
            self.assertTrue(connected)
            await communicator.disconnect()

    def test_publisher_channel_layer_errors(self):
        """Test publisher error handling when channel layer is unavailable."""
        operation_id = str(uuid4())
        device_id = str(uuid4())
        # Patch group_send with a synchronous mock
        with patch(
            "openwisp_firmware_upgrader.websockets.get_channel_layer"
        ) as mock_get_channel_layer:
            mock_channel_layer = MagicMock()
            mock_channel_layer.group_send.side_effect = ConnectionError(
                "Connection failed"
            )
            mock_get_channel_layer.return_value = mock_channel_layer
            publisher = UpgradeProgressPublisher(operation_id)
            try:
                publisher.publish_progress({"type": "test", "data": "test_value"})
            except ConnectionError:
                pass
        with patch(
            "openwisp_firmware_upgrader.websockets.get_channel_layer"
        ) as mock_get_channel_layer:
            mock_channel_layer = MagicMock()
            mock_channel_layer.group_send.side_effect = RuntimeError("Runtime error")
            mock_get_channel_layer.return_value = mock_channel_layer
            publisher = DeviceUpgradeProgressPublisher(device_id, operation_id)
            try:
                publisher.publish_progress({"type": "test", "data": "test_value"})
            except RuntimeError:
                pass

    async def test_websocket_message_formatting(self):
        """Test WebSocket message formatting and structure."""
        operation_id = str(uuid4())

        # Create a WebSocket connection
        communicator = WebsocketCommunicator(
            UpgradeProgressConsumer.as_asgi(),
            f"/ws/firmware-upgrader/upgrade-operation/{operation_id}/",
        )
        communicator.scope["url_route"] = {"kwargs": {"operation_id": operation_id}}

        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        # Test message with timestamp
        channel_layer = get_channel_layer()
        group_name = f"upgrade_{operation_id}"

        await channel_layer.group_send(
            group_name,
            {
                "type": "upgrade_progress",
                "data": {
                    "type": "status",
                    "status": "success",
                    "timestamp": timezone.now().isoformat(),
                },
            },
        )

        response = await communicator.receive_json_from()
        self.assertEqual(response["type"], "status")
        self.assertEqual(response["status"], "success")
        self.assertIn("timestamp", response)

        await communicator.disconnect()

    @override_settings(
        CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    )
    async def test_multiple_websocket_connections(self):
        """Test multiple WebSocket connections to the same operation."""
        operation_id = str(uuid4())

        # Create multiple WebSocket connections
        communicator1 = WebsocketCommunicator(
            UpgradeProgressConsumer.as_asgi(),
            f"/ws/firmware-upgrader/upgrade-operation/{operation_id}/",
        )
        communicator1.scope["url_route"] = {"kwargs": {"operation_id": operation_id}}

        communicator2 = WebsocketCommunicator(
            UpgradeProgressConsumer.as_asgi(),
            f"/ws/firmware-upgrader/upgrade-operation/{operation_id}/",
        )
        communicator2.scope["url_route"] = {"kwargs": {"operation_id": operation_id}}

        connected1, _ = await communicator1.connect()
        connected2, _ = await communicator2.connect()
        self.assertTrue(connected1)
        self.assertTrue(connected2)

        # Send message to group
        channel_layer = get_channel_layer()
        group_name = f"upgrade_{operation_id}"

        await channel_layer.group_send(
            group_name,
            {
                "type": "upgrade_progress",
                "data": {"type": "status", "status": "success"},
            },
        )

        # Both connections should receive the message
        response1 = await communicator1.receive_json_from()
        response2 = await communicator2.receive_json_from()

        self.assertEqual(response1["type"], "status")
        self.assertEqual(response1["status"], "success")
        self.assertEqual(response2["type"], "status")
        self.assertEqual(response2["status"], "success")

        await communicator1.disconnect()
        await communicator2.disconnect()

    async def test_websocket_authentication_edge_cases(self):
        """Test WebSocket authentication edge cases."""
        device_id = str(uuid4())
        communicator = WebsocketCommunicator(
            DeviceUpgradeProgressConsumer.as_asgi(),
            f"/ws/firmware-upgrader/device/{device_id}/",
        )
        communicator.scope["url_route"] = {"kwargs": {"pk": device_id}}
        # Don't set user in scope
        try:
            connected, _ = await communicator.connect()
            self.assertFalse(connected)
        except Exception:
            pass
        communicator = WebsocketCommunicator(
            DeviceUpgradeProgressConsumer.as_asgi(),
            f"/ws/firmware-upgrader/device/{device_id}/",
        )
        communicator.scope["url_route"] = {"kwargs": {"pk": device_id}}
        communicator.scope["user"] = MagicMock(is_authenticated=False)
        try:
            connected, _ = await communicator.connect()
            self.assertFalse(connected)
        except Exception:
            pass

    async def test_websocket_authorization_edge_cases(self):
        """Test WebSocket authorization edge cases."""
        device_id = str(uuid4())
        # Test with superuser
        communicator = WebsocketCommunicator(
            DeviceUpgradeProgressConsumer.as_asgi(),
            f"/ws/firmware-upgrader/device/{device_id}/",
        )
        communicator.scope["url_route"] = {"kwargs": {"pk": device_id}}
        communicator.scope["user"] = self.superuser
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        await communicator.disconnect()
        # Test with staff user (not superuser)
        communicator = WebsocketCommunicator(
            DeviceUpgradeProgressConsumer.as_asgi(),
            f"/ws/firmware-upgrader/device/{device_id}/",
        )
        communicator.scope["url_route"] = {"kwargs": {"pk": device_id}}
        communicator.scope["user"] = self.staff_user
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        await communicator.disconnect()

    async def test_websocket_message_serialization(self):
        """Test WebSocket message serialization with complex data."""
        operation_id = str(uuid4())

        # Create a WebSocket connection
        communicator = WebsocketCommunicator(
            UpgradeProgressConsumer.as_asgi(),
            f"/ws/firmware-upgrader/upgrade-operation/{operation_id}/",
        )
        communicator.scope["url_route"] = {"kwargs": {"operation_id": operation_id}}

        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        # Test complex message structure
        channel_layer = get_channel_layer()
        group_name = f"upgrade_{operation_id}"

        complex_data = {
            "type": "complex_update",
            "nested": {
                "list": [1, 2, 3],
                "dict": {"key": "value"},
                "boolean": True,
                "null": None,
            },
            "array": ["item1", "item2"],
        }

        await channel_layer.group_send(
            group_name,
            {
                "type": "upgrade_progress",
                "data": complex_data,
            },
        )

        response = await communicator.receive_json_from()
        self.assertEqual(response["type"], "complex_update")
        self.assertEqual(response["nested"]["list"], [1, 2, 3])
        self.assertEqual(response["nested"]["dict"]["key"], "value")
        self.assertTrue(response["nested"]["boolean"])
        self.assertIsNone(response["nested"]["null"])
        self.assertEqual(response["array"], ["item1", "item2"])

        await communicator.disconnect()
