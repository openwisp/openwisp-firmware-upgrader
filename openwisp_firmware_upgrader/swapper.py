from swapper import get_model_name as swapper_get_model_name
from swapper import load_model as swapper_load_model

from .apps import FirmwareUpdaterConfig as AppConfig


def load_model(model):
    return swapper_load_model(AppConfig.label, model)


def get_model_name(model):
    return swapper_get_model_name(AppConfig.label, model)
