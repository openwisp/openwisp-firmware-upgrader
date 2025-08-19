import logging
from pathlib import Path

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


def delete_file_and_cleanup(storage, file_path):
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
    except Exception as e:
        logger.error("Error deleting firmware file %s: %s", file_path, str(e))
        return False
    # Clean up parent directory if empty
    dir_path = str(Path(file_path).parent)
    if dir_path and dir_path != ".":
        try:
            dirs, files = storage.listdir(dir_path)
            if not dirs and not files:
                storage.delete(dir_path)
                logger.info("Deleted empty directory: %s", dir_path)
            else:
                logger.debug("Directory %s is not empty, skipping deletion", dir_path)
        except FileNotFoundError:
            logger.debug("Directory %s already removed", dir_path)
        except Exception as error:
            logger.warning("Could not delete directory %s: %s", dir_path, str(error))
    return True
