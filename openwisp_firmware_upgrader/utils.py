import logging

from django.utils.module_loading import import_string

from . import settings as app_settings

logger = logging.getLogger(__name__)


def get_upgrader_schema_for_device(device):
    upgrader_class = get_upgrader_class_for_device(device)
    return getattr(upgrader_class, 'SCHEMA', None)


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
        update_strategy__icontains='ssh',
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
