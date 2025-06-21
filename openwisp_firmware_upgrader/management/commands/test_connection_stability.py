import time
from django.core.management.base import BaseCommand
from openwisp_firmware_upgrader.websockets import DeviceUpgradeProgressPublisher


class Command(BaseCommand):
    help = 'Test WebSocket connection stability by sending continuous messages'

    def add_arguments(self, parser):
        parser.add_argument(
            'device_id',
            type=str,
            help='Device ID to test'
        )

    def handle(self, *args, **options):
        device_id = options['device_id']
        
        self.stdout.write(f"Testing connection stability for device: {device_id}")
        self.stdout.write("Will send messages every 2 seconds for 20 seconds...")
        self.stdout.write("Watch the server terminal for consumer debug messages!")
        
        publisher = DeviceUpgradeProgressPublisher(device_id)
        
        for i in range(10):
            try:
                message = f"Stability test message #{i+1} at {time.strftime('%H:%M:%S')}"
                publisher.publish_log(message, "in-progress")
                self.stdout.write(f"Sent message {i+1}: {message}")
                
                if i < 9:  # Don't sleep after the last message
                    time.sleep(2)
                    
            except Exception as e:
                self.stdout.write(f"Error sending message {i+1}: {e}")
        
        self.stdout.write("Test completed. Check server terminal for consumer debug messages.")
        self.stdout.write("If you see 🔥 messages in the server terminal, the consumer received them.")
        self.stdout.write("If not, the consumer is disconnecting before receiving messages.") 