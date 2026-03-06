import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from swapper import load_model

from ..websockets import (
    BatchUpgradeProgressConsumer,
    BatchUpgradeProgressPublisher,
    DeviceUpgradeProgressConsumer,
    UpgradeProgressConsumer,
    UpgradeProgressPublisher,
)
from .base import TestUpgraderMixin

User = get_user_model()
UpgradeOperation = load_model("firmware_upgrader", "UpgradeOperation")
BatchUpgradeOperation = load_model("firmware_upgrader", "BatchUpgradeOperation")
Device = load_model("config", "Device")


@pytest.mark.asyncio
class TestFirmwareUpgradeSockets(TestUpgraderMixin, TransactionTestCase):
    """Test WebSocket consumers and publishers for firmware upgrade progress."""

    _mock_upgrade = "openwisp_firmware_upgrader.upgraders.openwrt.OpenWrt.upgrade"
    _mock_connect = "openwisp_controller.connection.models.DeviceConnection.connect"

    def setUp(self):
        super().setUp()
        self.regular_user = self._create_user()
        self.superuser = self._create_admin()

    def tearDown(self):
        super().tearDown()

    async def _create_test_device_with_upgrade(self):
        """Helper to create a device with an upgrade operation."""
        await sync_to_async(self._create_device_firmware)(upgrade=True)
        upgrade_operation = await sync_to_async(
            UpgradeOperation.objects.values("id", "device_id").first
        )()
        return str(upgrade_operation["id"]), str(upgrade_operation["device_id"])

    async def _create_administrator(self, organizations=None, **kwargs):
        organizations = organizations or [await sync_to_async(self._get_org)()]
        administrator = await sync_to_async(super()._create_administrator)(
            organizations, **kwargs
        )
        perms = await sync_to_async(list)(
            Permission.objects.filter(
                codename__in=[
                    f"change_{Device._meta.model_name}",
                    f"change_{UpgradeOperation._meta.model_name}",
                ]
            ).values_list("pk", flat=True)
        )
        await sync_to_async(administrator.user_permissions.add)(*perms)
        return administrator

    async def _get_upgrade_progress_communicator(self, operation_id, user=None):
        """
        Helper method to create and connect a WebSocket communicator
        for UpgradeProgressConsumer.
        """
        if user is None:
            user = self.superuser
        communicator = WebsocketCommunicator(
            UpgradeProgressConsumer.as_asgi(),
            f"/ws/firmware-upgrader/upgrade-operation/{operation_id}/",
        )
        communicator.scope["url_route"] = {"kwargs": {"operation_id": operation_id}}
        communicator.scope["user"] = user
        connected, _ = await communicator.connect()
        assert connected is True
        return communicator

    async def _get_batch_upgrade_progress_communicator(self, batch_id, user=None):
        """
        Helper method to create and connect a WebSocket communicator
        for BatchUpgradeProgressConsumer.
        """
        if user is None:
            user = self.superuser
        communicator = WebsocketCommunicator(
            BatchUpgradeProgressConsumer.as_asgi(),
            f"/ws/firmware-upgrader/batch-upgrade-operation/{batch_id}/",
        )
        communicator.scope["url_route"] = {"kwargs": {"batch_id": batch_id}}
        communicator.scope["user"] = user
        connected, _ = await communicator.connect()
        assert connected is True
        return communicator

    async def _get_device_upgrade_progress_communicator(self, device_id, user=None):
        """
        Helper method to create and connect a WebSocket communicator
        for DeviceUpgradeProgressConsumer.
        """
        if user is None:
            user = self.superuser
        communicator = WebsocketCommunicator(
            DeviceUpgradeProgressConsumer.as_asgi(),
            f"/ws/firmware-upgrader/device/{device_id}/",
        )
        communicator.scope["url_route"] = {"kwargs": {"device_id": device_id}}
        communicator.scope["user"] = user
        connected, _ = await communicator.connect()
        assert connected is True
        return communicator

    @patch(_mock_upgrade, return_value=True)
    @patch(_mock_connect, return_value=True)
    async def test_upgrade_progress_consumer_connection(self, *args):
        """Test UpgradeProgressConsumer connection"""
        operation_id, _ = await self._create_test_device_with_upgrade()
        communicator = await self._get_upgrade_progress_communicator(operation_id)
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
        build = await sync_to_async(self._get_build)()
        batch = await sync_to_async(BatchUpgradeOperation.objects.create)(build=build)
        batch_id = str(batch.pk)
        communicator = await self._get_batch_upgrade_progress_communicator(batch_id)
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

    @patch(_mock_upgrade, return_value=True)
    @patch(_mock_connect, return_value=True)
    async def test_device_upgrade_progress_consumer_connection_authenticated(
        self, *args
    ):
        """Test DeviceUpgradeProgressConsumer with authenticated user."""
        _, device_id = await self._create_test_device_with_upgrade()
        communicator = await self._get_device_upgrade_progress_communicator(device_id)
        # Test receiving messages
        channel_layer = get_channel_layer()
        group_name = f"firmware_upgrader.device-{device_id}"
        # Send operation update message
        await channel_layer.group_send(
            group_name,
            {
                "type": "send_update",
                "data": {
                    "type": "operation_update",
                    "operation": {
                        "id": "test-op-id",
                        "status": "in-progress",
                        "log": "Test log",
                    },
                    "timestamp": timezone.now().isoformat(),
                },
            },
        )
        response = await communicator.receive_json_from()
        self.assertEqual(response["type"], "operation_update")
        self.assertEqual(response["operation"]["id"], "test-op-id")
        await communicator.disconnect()

    @patch(_mock_upgrade, return_value=True)
    @patch(_mock_connect, return_value=True)
    async def test_device_upgrade_progress_consumer_connection_unauthenticated(
        self, *args
    ):
        """Test DeviceUpgradeProgressConsumer with unauthenticated user."""
        _, device_id = await self._create_test_device_with_upgrade()
        unauthenticated_user = MagicMock(is_authenticated=False)
        communicator = WebsocketCommunicator(
            DeviceUpgradeProgressConsumer.as_asgi(),
            f"/ws/firmware-upgrader/device/{device_id}/",
        )
        communicator.scope["url_route"] = {"kwargs": {"device_id": device_id}}
        communicator.scope["user"] = unauthenticated_user
        connected, _ = await communicator.connect()
        self.assertFalse(connected)

    @patch(_mock_upgrade, return_value=True)
    @patch(_mock_connect, return_value=True)
    async def test_device_upgrade_progress_consumer_connection_unauthorized(
        self, *args
    ):
        """Test DeviceUpgradeProgressConsumer with unauthorized user."""
        _, device_id = await self._create_test_device_with_upgrade()
        communicator = WebsocketCommunicator(
            DeviceUpgradeProgressConsumer.as_asgi(),
            f"/ws/firmware-upgrader/device/{device_id}/",
        )
        communicator.scope["url_route"] = {"kwargs": {"device_id": device_id}}
        communicator.scope["user"] = self.regular_user
        connected, _ = await communicator.connect()
        self.assertFalse(connected)

    @patch(_mock_upgrade, return_value=True)
    @patch(_mock_connect, return_value=True)
    async def test_device_upgrade_progress_consumer_current_state_request(self, *args):
        """Test DeviceUpgradeProgressConsumer current state request functionality."""
        _, device_id = await self._create_test_device_with_upgrade()
        communicator = await self._get_device_upgrade_progress_communicator(device_id)
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
                "status": "in-progress",
                "log": "Test log 2",
                "modified": timezone.now(),
                "created": timezone.now(),
            },
        ]
        with patch(
            "openwisp_firmware_upgrader.websockets.sync_to_async"
        ) as mock_sync_to_async:
            mock_sync_to_async.return_value = AsyncMock(return_value=test_operations)
            # Send current state request
            await communicator.send_json_to({"type": "request_current_state"})
            # The consumer should send current state for each operation
            response1 = await communicator.receive_json_from()
            response2 = await communicator.receive_json_from()
            self.assertEqual(response1["type"], "operation_update")
            self.assertEqual(response1["operation"]["id"], "op1")
            self.assertEqual(response2["type"], "operation_update")
            self.assertEqual(response2["operation"]["id"], "op2")
        await communicator.disconnect()

    @patch(_mock_upgrade, return_value=True)
    @patch(_mock_connect, return_value=True)
    async def test_device_upgrade_progress_consumer_unknown_message(self, *args):
        """Test DeviceUpgradeProgressConsumer handling of unknown message types."""
        _, device_id = await self._create_test_device_with_upgrade()
        communicator = await self._get_device_upgrade_progress_communicator(device_id)
        # Patch the logger at the correct import path
        with patch("openwisp_firmware_upgrader.websockets.logger") as mock_logger:
            await communicator.send_json_to({"type": "unknown_message_type"})
            # Allow event loop to process
            await communicator.receive_nothing()
            mock_logger.warning.assert_called()
        await communicator.disconnect()

    def test_device_upgrade_progress_publisher(self):
        """Test UpgradeProgressPublisher functionality."""
        device_id = str(uuid4())
        operation_id = str(uuid4())
        publisher = UpgradeProgressPublisher(device_id, operation_id)
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
        publisher_no_op = UpgradeProgressPublisher(device_id)
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
        connected, _ = await communicator.connect()
        self.assertEqual(connected, False)

    @override_settings(
        CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    )
    @patch(_mock_upgrade, return_value=True)
    @patch(_mock_connect, return_value=True)
    async def test_websocket_with_inmemory_channel_layer(self, *args):
        """Test WebSocket functionality with in-memory channel layer."""
        operation_id, _ = await self._create_test_device_with_upgrade()
        communicator = await self._get_upgrade_progress_communicator(
            operation_id, user=self.superuser
        )
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

    @override_settings(
        CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    )
    @patch(_mock_upgrade, return_value=True)
    @patch(_mock_connect, return_value=True)
    async def test_websocket_disconnect_handling(self, *args):
        """Test WebSocket disconnect handling."""
        operation_id, _ = await self._create_test_device_with_upgrade()
        communicator = await self._get_upgrade_progress_communicator(
            operation_id, user=self.superuser
        )
        # Test disconnect
        await communicator.disconnect()

    @patch(_mock_upgrade, return_value=True)
    @patch(_mock_connect, return_value=True)
    async def test_device_upgrade_progress_consumer_channel_layer_errors(self, *args):
        """Test DeviceUpgradeProgressConsumer channel layer error handling."""
        _, device_id = await self._create_test_device_with_upgrade()
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
            communicator.scope["url_route"] = {"kwargs": {"device_id": device_id}}
            communicator.scope["user"] = self.superuser
            try:
                await communicator.connect()
            except ConnectionError:
                pass
        with patch.object(
            DeviceUpgradeProgressConsumer, "channel_layer", create=True
        ) as mock_channel_layer:
            mock_channel_layer.group_add.side_effect = RuntimeError("Runtime error")
            communicator = WebsocketCommunicator(
                DeviceUpgradeProgressConsumer.as_asgi(),
                f"/ws/firmware-upgrader/device/{device_id}/",
            )
            communicator.scope["url_route"] = {"kwargs": {"device_id": device_id}}
            communicator.scope["user"] = self.superuser
            try:
                await communicator.connect()
            except ConnectionError:
                pass

    @patch(_mock_upgrade, return_value=True)
    @patch(_mock_connect, return_value=True)
    async def test_device_upgrade_progress_consumer_disconnect_error_handling(
        self, *args
    ):
        """Test DeviceUpgradeProgressConsumer disconnect error handling."""
        _, device_id = await self._create_test_device_with_upgrade()
        with patch.object(
            DeviceUpgradeProgressConsumer, "channel_layer", create=True
        ) as mock_channel_layer:
            mock_channel_layer.group_discard.side_effect = AttributeError(
                "No channel layer"
            )
            communicator = await self._get_device_upgrade_progress_communicator(
                device_id
            )
            await communicator.disconnect()

    @patch(_mock_upgrade, return_value=True)
    @patch(_mock_connect, return_value=True)
    async def test_websocket_message_formatting(self, *args):
        """Test WebSocket message formatting and structure."""
        operation_id, _ = await self._create_test_device_with_upgrade()
        communicator = await self._get_upgrade_progress_communicator(
            operation_id, user=self.superuser
        )
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

    @patch(_mock_upgrade, return_value=True)
    @patch(_mock_connect, return_value=True)
    async def test_multiple_websocket_connections(self, *args):
        """Test multiple WebSocket connections to the same operation."""
        org_manager = await self._create_administrator()
        operation_id, _ = await self._create_test_device_with_upgrade()

        # Create multiple WebSocket connections using helper method
        communicator1 = await self._get_upgrade_progress_communicator(
            operation_id, user=self.superuser
        )
        communicator2 = await self._get_upgrade_progress_communicator(
            operation_id, user=org_manager
        )
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

    @patch(_mock_upgrade, return_value=True)
    @patch(_mock_connect, return_value=True)
    async def test_websocket_authentication_edge_cases(self, *args):
        """Test WebSocket authentication edge cases."""
        _, device_id = await self._create_test_device_with_upgrade()
        communicator = WebsocketCommunicator(
            DeviceUpgradeProgressConsumer.as_asgi(),
            f"/ws/firmware-upgrader/device/{device_id}/",
        )
        communicator.scope["url_route"] = {"kwargs": {"device_id": device_id}}
        # Don't set user in scope
        connected, _ = await communicator.connect()
        self.assertFalse(connected)
        communicator = WebsocketCommunicator(
            DeviceUpgradeProgressConsumer.as_asgi(),
            f"/ws/firmware-upgrader/device/{device_id}/",
        )
        communicator.scope["url_route"] = {"kwargs": {"device_id": device_id}}
        communicator.scope["user"] = MagicMock(is_authenticated=False)
        connected, _ = await communicator.connect()
        self.assertFalse(connected)

    @patch(_mock_upgrade, return_value=True)
    @patch(_mock_connect, return_value=True)
    async def test_websocket_authorization_edge_cases(self, *args):
        """Test WebSocket authorization edge cases."""
        org_manager = await self._create_administrator()
        _, device_id = await self._create_test_device_with_upgrade()
        # Test with superuser using helper method
        communicator = await self._get_device_upgrade_progress_communicator(
            device_id, user=self.superuser
        )
        await communicator.disconnect()
        # Test with staff user (not superuser) using helper method
        communicator = await self._get_device_upgrade_progress_communicator(
            device_id, user=org_manager
        )
        await communicator.disconnect()

    @override_settings(
        CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    )
    @patch(_mock_upgrade, return_value=True)
    @patch(_mock_connect, return_value=True)
    async def test_websocket_message_serialization(self, *args):
        """Test WebSocket message serialization with complex data."""
        operation_id, _ = await self._create_test_device_with_upgrade()
        communicator = await self._get_upgrade_progress_communicator(
            operation_id, user=self.superuser
        )

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
        self.assertEqual(response["nested"]["boolean"], True)
        self.assertIsNone(response["nested"]["null"])
        self.assertEqual(response["array"], ["item1", "item2"])
        await communicator.disconnect()

    @override_settings(
        CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    )
    @patch(_mock_upgrade, return_value=True)
    @patch(_mock_connect, return_value=True)
    async def test_no_duplicate_messages_on_log_line_with_batch(self, *args):
        """
        Test that calling log() on an UpgradeOperation associated with a
        BatchUpgradeOperation does not send duplicate messages to the
        operation-specific WebSocket channel.
        """
        # Create a batch upgrade operation
        build = await sync_to_async(self._get_build)()
        batch = await sync_to_async(BatchUpgradeOperation.objects.create)(build=build)
        # Create device firmware with upgrade operation linked to the batch
        device_fw = await sync_to_async(self._create_device_firmware)(upgrade=False)
        operation = await sync_to_async(UpgradeOperation.objects.create)(
            device=device_fw.device,
            image=device_fw.image,
            batch=batch,
            status="in-progress",
        )
        operation_id = str(operation.pk)
        communicator = await self._get_upgrade_progress_communicator(
            operation_id, user=self.superuser
        )
        await sync_to_async(operation.log_line)(
            "The upgrade operation will be retried soon."
        )
        messages = []
        try:
            # Try to receive messages for a short period
            for _ in range(5):  # Try up to 5 times
                response = await asyncio.wait_for(
                    communicator.receive_json_from(), timeout=0.5
                )
                messages.append(response)
        except asyncio.TimeoutError:
            # No more messages available, which is expected
            pass
        # Assert that we received exactly ONE log message (not duplicates)
        self.assertEqual(len(messages), 1)
        await communicator.disconnect()
