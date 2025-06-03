from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.test import TestCase

from ..swapper import load_model
from ..websockets import UpgradeProgressConsumer, BatchUpgradeProgressConsumer
from .base import TestUpgraderMixin

UpgradeOperation = load_model("UpgradeOperation")


class WebSocketTest(TestUpgraderMixin, TestCase):
    async def test_upgrade_progress_consumer(self):
        # Create test environment
        env = await sync_to_async(self._create_upgrade_env)(device_firmware=True)
        device = env["d1"]
        image = env["image2a"]

        # Create a test upgrade operation
        operation = await self._create_test_upgrade_operation(device, image)

        # Create a WebSocket connection with proper URL routing
        communicator = WebsocketCommunicator(
            UpgradeProgressConsumer.as_asgi(), f"/ws/upgrade/{operation.id}/"
        )
        # Add URL route parameters to the scope
        communicator.scope["url_route"] = {
            "kwargs": {"operation_id": str(operation.id)}
        }

        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        # Get channel layer
        channel_layer = get_channel_layer()
        group_name = f"upgrade_{operation.id}"

        # Send initial status message
        await channel_layer.group_send(
            group_name,
            {
                "type": "upgrade_progress",
                "data": {"type": "status", "status": "in-progress"},
            },
        )

        # Receive initial status message
        initial_response = await communicator.receive_json_from()
        self.assertEqual(initial_response["type"], "status")
        self.assertEqual(initial_response["status"], "in-progress")

        # Test receiving progress updates
        await channel_layer.group_send(
            group_name,
            {
                "type": "upgrade_progress",
                "data": {"type": "log", "message": "Test progress message"},
            },
        )
        response = await communicator.receive_json_from()
        self.assertEqual(response["type"], "log")
        self.assertEqual(response["message"], "Test progress message")

        # Test receiving status updates
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

        # Close the connection
        await communicator.disconnect()

    async def _create_test_upgrade_operation(self, device, image):
        operation = await UpgradeOperation.objects.acreate(
            device=device, image=image, status="in-progress"
        )
        return operation

    async def test_batch_upgrade_progress_consumer(self):
        # Create test environment
        env = await sync_to_async(self._create_upgrade_env)(device_firmware=True)
        build = env["build2"]

        # Create a test batch upgrade operation
        BatchUpgradeOperation = load_model("BatchUpgradeOperation")
        batch = await sync_to_async(BatchUpgradeOperation.objects.create)(build=build)

        # Create a WebSocket connection with proper URL routing
        communicator = WebsocketCommunicator(
            BatchUpgradeProgressConsumer.as_asgi(), f"/ws/batch-upgrade/{batch.id}/"
        )
        # Add URL route parameters to the scope
        communicator.scope["url_route"] = {
            "kwargs": {"batch_id": str(batch.id)}
        }

        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        # Get channel layer
        channel_layer = get_channel_layer()
        group_name = f"batch_upgrade_{batch.id}"

        # Send initial batch status message
        await channel_layer.group_send(
            group_name,
            {
                "type": "batch_upgrade_progress",
                "data": {"type": "batch_status", "status": "in-progress", "completed": 0, "total": 2},
            },
        )

        # Receive initial batch status message
        initial_response = await communicator.receive_json_from()
        self.assertEqual(initial_response["type"], "batch_status")
        self.assertEqual(initial_response["status"], "in-progress")
        self.assertEqual(initial_response["completed"], 0)
        self.assertEqual(initial_response["total"], 2)

        # Test receiving operation progress updates
        await channel_layer.group_send(
            group_name,
            {
                "type": "batch_upgrade_progress",
                "data": {"type": "operation_progress", "operation_id": "op1", "status": "in-progress", "progress": 50},
            },
        )
        response = await communicator.receive_json_from()
        self.assertEqual(response["type"], "operation_progress")
        self.assertEqual(response["operation_id"], "op1")
        self.assertEqual(response["status"], "in-progress")
        self.assertEqual(response["progress"], 50)

        # Test receiving batch status updates
        await channel_layer.group_send(
            group_name,
            {
                "type": "batch_upgrade_progress",
                "data": {"type": "batch_status", "status": "success", "completed": 2, "total": 2},
            },
        )
        response = await communicator.receive_json_from()
        self.assertEqual(response["type"], "batch_status")
        self.assertEqual(response["status"], "success")
        self.assertEqual(response["completed"], 2)
        self.assertEqual(response["total"], 2)

        # Close the connection
        await communicator.disconnect()
