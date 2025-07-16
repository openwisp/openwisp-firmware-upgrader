import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from .signals import firmware_upgrader_log_updated
from .websockets import DeviceUpgradeProgressPublisher, UpgradeProgressPublisher

logger = logging.getLogger(__name__)


@receiver(firmware_upgrader_log_updated)
def handle_firmware_upgrader_log_updated(sender, instance, line, **kwargs):
    """
    Handle log line events by publishing to WebSocket channels.
    """
    try:
        # Publish to operation-specific channel
        publisher = UpgradeProgressPublisher(instance.pk)
        publisher.publish_progress(
            {"type": "log", "content": line, "status": instance.status}
        )

        # Publish to device-specific channel for real-time UI updates
        device_publisher = DeviceUpgradeProgressPublisher(
            instance.device.pk, instance.pk
        )
        device_publisher.publish_log(line, instance.status)

    except (ConnectionError, TimeoutError) as e:
        logger.error(
            f"Failed to connect to channel layer for upgrade operation {instance.pk}: {e}",
            exc_info=True,
        )
    except RuntimeError as e:
        logger.error(
            f"Runtime error in WebSocket publishing for upgrade operation {instance.pk}: {e}",
            exc_info=True,
        )


def handle_upgrade_operation_saved(sender, instance, created, **kwargs):
    """
    Handle UpgradeOperation post_save events by publishing status updates to WebSocket channels.
    """
    # Only publish updates for existing operations
    if created:
        return

    try:
        # Publish status update to operation-specific channel
        publisher = UpgradeProgressPublisher(instance.pk)
        publisher.publish_progress({"type": "status", "status": instance.status})

        # Publish complete operation update to device-specific channel
        device_publisher = DeviceUpgradeProgressPublisher(
            instance.device.pk, instance.pk
        )
        device_publisher.publish_operation_update(
            {
                "id": str(instance.pk),
                "device": str(instance.device.pk),
                "status": instance.status,
                "log": instance.log,
                "progress": getattr(
                    instance, "progress", 0
                ),  # Include progress field
                "image": (
                    str(getattr(instance.image, "pk", None))
                    if getattr(instance.image, "pk", None)
                    else None
                ),
                "modified": (
                    instance.modified.isoformat() if instance.modified else None
                ),
                "created": (
                    instance.created.isoformat() if instance.created else None
                ),
            }
        )
    except (ConnectionError, TimeoutError) as e:
        logger.error(
            f"Failed to connect to channel layer for upgrade operation {instance.pk}: {e}",
            exc_info=True,
        )
    except RuntimeError as e:
        logger.error(
            f"Runtime error in WebSocket publishing for upgrade operation {instance.pk}: {e}",
            exc_info=True,
        )
