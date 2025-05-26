from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.test import TestCase

from openwisp_firmware_upgrader.swapper import load_model
from openwisp_firmware_upgrader.tests.base import TestUpgraderMixin
from openwisp_firmware_upgrader.websockets import UpgradeProgressConsumer

UpgradeOperation = load_model('UpgradeOperation')


class WebSocketTest(TestUpgraderMixin, TestCase):
    async def test_upgrade_progress_consumer(self):
        # Create test environment
        env = await sync_to_async(self._create_upgrade_env)(device_firmware=True)
        device = env['d1']
        image = env['image2a']

        # Create a test upgrade operation
        operation = await self._create_test_upgrade_operation(device, image)

        # Create a WebSocket connection with proper URL routing
        communicator = WebsocketCommunicator(
            UpgradeProgressConsumer.as_asgi(), f"/ws/upgrade/{operation.id}/"
        )
        # Add URL route parameters to the scope
        communicator.scope['url_route'] = {
            'kwargs': {'operation_id': str(operation.id)}
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
                'type': 'upgrade_progress',
                'data': {'type': 'status', 'status': 'in-progress'},
            },
        )

        # Receive initial status message
        initial_response = await communicator.receive_json_from()
        self.assertEqual(initial_response['type'], 'status')
        self.assertEqual(initial_response['status'], 'in-progress')

        # Test receiving progress updates
        await channel_layer.group_send(
            group_name,
            {
                'type': 'upgrade_progress',
                'data': {'type': 'log', 'message': 'Test progress message'},
            },
        )
        response = await communicator.receive_json_from()
        self.assertEqual(response['type'], 'log')
        self.assertEqual(response['message'], 'Test progress message')

        # Test receiving status updates
        await channel_layer.group_send(
            group_name,
            {
                'type': 'upgrade_progress',
                'data': {'type': 'status', 'status': 'success'},
            },
        )
        response = await communicator.receive_json_from()
        self.assertEqual(response['type'], 'status')
        self.assertEqual(response['status'], 'success')

        # Close the connection
        await communicator.disconnect()

    async def _create_test_upgrade_operation(self, device, image):
        operation = await UpgradeOperation.objects.acreate(
            device=device, image=image, status='in-progress'
        )
        return operation
