from swapper import load_model

from openwisp_controller.connection.tests.pytest import (
    TestCommandsConsumer as BaseTestCommandsConsumer,
)

Command = load_model("connection", "Command")


class TestCommandsConsumer(BaseTestCommandsConsumer):
    app_label = Command._meta.app_label


del BaseTestCommandsConsumer
