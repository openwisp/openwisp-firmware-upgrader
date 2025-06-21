import asyncio
import logging
from django.core.management.base import BaseCommand
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Test channel layer and check for connected WebSocket consumers'

    def add_arguments(self, parser):
        parser.add_argument(
            'device_id',
            type=str,
            help='Device ID to test'
        )

    def handle(self, *args, **options):
        device_id = options['device_id']
        group_name = f"firmware_upgrader.device-{device_id}"
        
        self.stdout.write(f"Testing channel layer for device: {device_id}")
        self.stdout.write(f"Group name: {group_name}")
        
        # Get channel layer
        channel_layer = get_channel_layer()
        self.stdout.write(f"Channel layer backend: {channel_layer.__class__.__name__}")
        
        # Test if channel layer is working
        try:
            # Send a test message directly to the group
            async_to_sync(channel_layer.group_send)(
                group_name,
                {
                    "type": "send_update",
                    "model": "UpgradeOperation", 
                    "data": {
                        "type": "log",
                        "content": "Direct channel layer test message",
                        "status": "in-progress"
                    }
                }
            )
            self.stdout.write("✓ Channel layer group_send executed successfully")
            
            # Test basic channel layer functionality
            test_channel = "test-channel"
            test_message = {"type": "test.message", "text": "hello"}
            
            async_to_sync(channel_layer.send)(test_channel, test_message)
            received = async_to_sync(channel_layer.receive)(test_channel)
            
            if received == test_message:
                self.stdout.write("✓ Channel layer send/receive working correctly")
            else:
                self.stdout.write(f"✗ Channel layer test failed. Sent: {test_message}, Received: {received}")
                
        except Exception as e:
            self.stdout.write(f"✗ Channel layer test failed: {e}")
            
        # Check if there are any groups with consumers
        try:
            # This is a bit hacky but can help debug
            if hasattr(channel_layer, 'groups'):
                self.stdout.write(f"Active groups: {list(channel_layer.groups.keys())}")
            else:
                self.stdout.write("Cannot inspect active groups (InMemoryChannelLayer limitation)")
        except Exception as e:
            self.stdout.write(f"Could not inspect groups: {e}")
            
        self.stdout.write("\nNow check your browser console for messages!")
        self.stdout.write("If you don't see the test message, the issue is likely:")
        self.stdout.write("1. WebSocket consumer not properly connected to the group")
        self.stdout.write("2. Consumer authentication/authorization issue")
        self.stdout.write("3. Message type/format issue in consumer") 