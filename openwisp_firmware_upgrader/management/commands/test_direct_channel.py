import asyncio
from django.core.management.base import BaseCommand
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync


class Command(BaseCommand):
    help = 'Test sending messages directly to consumer channel (bypass groups)'

    def add_arguments(self, parser):
        parser.add_argument(
            'device_id',
            type=str,
            help='Device ID to test'
        )

    def handle(self, *args, **options):
        device_id = options['device_id']
        group_name = f"firmware_upgrader.device-{device_id}"
        
        self.stdout.write(f"Testing direct channel messaging for device: {device_id}")
        self.stdout.write(f"Group name: {group_name}")
        
        channel_layer = get_channel_layer()
        
        # First, let's try to see what channels exist
        self.stdout.write("\n=== CHECKING CHANNEL LAYER STATE ===")
        
        try:
            # Test basic channel layer functionality first
            test_channel = "test-channel-direct"
            test_message = {
                "type": "send_update",
                "model": "UpgradeOperation",
                "data": {"type": "log", "content": "Direct test message"}
            }
            
            async_to_sync(channel_layer.send)(test_channel, test_message)
            received = async_to_sync(channel_layer.receive)(test_channel)
            
            if received:
                self.stdout.write("✓ Basic channel layer send/receive works")
            else:
                self.stdout.write("✗ Basic channel layer send/receive failed")
                
        except Exception as e:
            self.stdout.write(f"✗ Channel layer test failed: {e}")
            
        # Now test group functionality
        self.stdout.write("\n=== TESTING GROUP FUNCTIONALITY ===")
        
        try:
            # Send a test message to the group
            group_message = {
                "type": "send_update",
                "model": "UpgradeOperation", 
                "data": {
                    "type": "log",
                    "content": "DIRECT GROUP TEST - If you see this, groups work!",
                    "status": "in-progress"
                }
            }
            
            async_to_sync(channel_layer.group_send)(group_name, group_message)
            self.stdout.write("✓ Group send executed")
            
            # Wait a moment for processing
            import time
            time.sleep(1)
            
            self.stdout.write("\nIf the consumer received this message, you should see:")
            self.stdout.write("🔥 CONSUMER RECEIVED MESSAGE in server terminal")
            self.stdout.write("The test message in browser console")
            
        except Exception as e:
            self.stdout.write(f"✗ Group send failed: {e}")
            
        # Try to inspect the channel layer internals
        self.stdout.write("\n=== CHANNEL LAYER INSPECTION ===")
        
        try:
            if hasattr(channel_layer, 'groups'):
                groups = getattr(channel_layer, 'groups', {})
                self.stdout.write(f"Active groups: {list(groups.keys())}")
                
                if group_name in groups:
                    channels_in_group = groups[group_name]
                    self.stdout.write(f"Channels in {group_name}: {channels_in_group}")
                else:
                    self.stdout.write(f"Group {group_name} not found in active groups")
            else:
                self.stdout.write("Cannot inspect channel layer groups")
                
        except Exception as e:
            self.stdout.write(f"Group inspection failed: {e}")
            
        self.stdout.write(f"\nTest completed. Check server terminal for 🔥 messages!") 