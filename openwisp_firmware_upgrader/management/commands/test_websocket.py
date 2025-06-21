import logging
import time

from django.core.management.base import BaseCommand

from openwisp_firmware_upgrader.websockets import DeviceUpgradeProgressPublisher

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Test WebSocket publishing for firmware upgrade progress"

    def add_arguments(self, parser):
        parser.add_argument(
            "device_id", type=str, help="Device ID to test WebSocket publishing for"
        )
        parser.add_argument(
            "--operation-id", type=str, help="Operation ID (optional)", default=None
        )

    def handle(self, *args, **options):
        device_id = options["device_id"]
        operation_id = options.get("operation_id")

        self.stdout.write(f"Testing WebSocket publishing for device: {device_id}")

        # Create publisher
        publisher = DeviceUpgradeProgressPublisher(device_id, operation_id)

        # Debug group names
        self.stdout.write(f"Publisher device group name: {publisher.device_group_name}")
        if hasattr(publisher, "operation_group_name"):
            self.stdout.write(
                f"Publisher operation group name: {publisher.operation_group_name}"
            )
        self.stdout.write(
            f"Expected consumer group name: firmware_upgrader.device-{device_id}"
        )

        # Test different types of messages
        test_messages = [
            {
                "method": "publish_log",
                "args": ["Test log message from management command", "in-progress"],
                "description": "Log message",
            },
            {
                "method": "publish_status",
                "args": ["in-progress"],
                "description": "Status update",
            },
            {
                "method": "publish_operation_update",
                "args": [
                    {
                        "id": operation_id or "test-operation",
                        "device": device_id,
                        "status": "in-progress",
                        "log": "Test operation update from management command",
                        "image": None,
                        "modified": time.time(),
                        "created": time.time(),
                    }
                ],
                "description": "Operation update",
            },
        ]

        for i, message in enumerate(test_messages, 1):
            self.stdout.write(f"\n{i}. Sending {message['description']}...")
            try:
                method = getattr(publisher, message["method"])
                method(*message["args"])
                self.stdout.write(f"   ✓ {message['description']} sent successfully")
            except Exception as e:
                self.stdout.write(f"   ✗ Failed to send {message['description']}: {e}")

            # Small delay between messages
            time.sleep(1)

        self.stdout.write(
            f"\nTest completed. Check your browser console for WebSocket messages."
        )
        self.stdout.write(
            "If you don't see messages in the browser, check:\n"
            "1. WebSocket connection is open\n"
            "2. User authentication/authorization\n"
            "3. Django Channels configuration\n"
            "4. Channel layer (Redis/In-memory)"
        )
