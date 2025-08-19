import logging
from functools import partial
from pathlib import Path

from django.db import transaction
from django.utils.module_loading import import_string

from . import settings as app_settings

logger = logging.getLogger(__name__)


def get_upgrader_schema_for_device(device):
    upgrader_class = get_upgrader_class_for_device(device)
    return getattr(upgrader_class, "SCHEMA", None)


def get_upgrader_class_for_device(device):
    """
    Returns firmware upgrader class for a device depending
    on update_strategy of device's DeviceConnection.

    It only takes the first DeviceConnection object into consideration.
    This function makes the following assumptions:
        - a device cannot have DeviceConnection objects of
          two different update_strategy.
        - an upgrade cannot be performed on a device without a
          device connection
    """
    device_conn = device.deviceconnection_set.filter(
        update_strategy__icontains="ssh",
        enabled=True,
    ).first()
    if not device_conn:
        raise device.deviceconnection_set.model.DoesNotExist
    return get_upgrader_class_from_device_connection(device_conn)


def get_upgrader_class_from_device_connection(device_conn):
    try:
        upgrader_class = app_settings.UPGRADERS_MAP[device_conn.update_strategy]
        upgrader_class = import_string(upgrader_class)
    except (AttributeError, ImportError, KeyError) as e:
        logger.exception(e)
        return
    return upgrader_class


def delete_file_with_cleanup(storage, file_path):
    """
    Delete a file and clean up its parent directory if empty.

    Args:
        storage: Django storage backend instance
        file_path (str): Path to the file to delete (relative to storage root)

    Returns:
        bool: True if file was successfully deleted, False otherwise

    This function:
        - Deletes the specified file using the storage backend
        - Checks the parent directory after deletion
        - Removes the parent directory if it's empty
        - Logs appropriate messages for each action
        - Handles exceptions gracefully without raising them
    """
    try:
        storage.delete(file_path)
        logger.info("Deleted firmware file: %s", file_path)

        # Clean up parent directory if empty
        dir_path = str(Path(file_path).parent)
        if dir_path and dir_path != ".":
            try:
                dirs, files = storage.listdir(dir_path)
                if not dirs and not files:
                    storage.delete(dir_path)
                    logger.info("Deleted empty directory: %s", dir_path)
                else:
                    logger.debug(
                        "Directory %s is not empty, skipping deletion", dir_path
                    )
            except FileNotFoundError:
                logger.debug("Directory %s already removed", dir_path)
            except Exception as error:
                logger.warning(
                    "Could not delete directory %s: %s", dir_path, str(error)
                )

        return True

    except Exception as e:
        logger.error("Error deleting firmware file %s: %s", file_path, str(e))
        return False


def schedule_firmware_file_deletion(firmware_image_class, **filter_kwargs):
    """
    Utility function to schedule deletion of firmware image files.

    Args:
        firmware_image_class: The FirmwareImage model class
        **filter_kwargs: Django ORM filter arguments to find the firmware images

    This function:
        - Queries firmware images based on the provided filter kwargs
        - Collects file paths from images that have files
        - Schedules asynchronous deletion of collected files after transaction commit
        - Uses the delete_firmware_files Celery task for actual deletion
    """
    from .tasks import delete_firmware_files  # Import here to avoid circular imports

    files_to_delete = []

    # Get all firmware images matching the filter criteria
    for image in firmware_image_class.objects.iterator(**filter_kwargs):
        if image.file and image.file.name:
            files_to_delete.append(image.file.name)

    # Schedule file deletion after transaction is committed
    if files_to_delete:
        transaction.on_commit(partial(delete_firmware_files.delay, files_to_delete))
