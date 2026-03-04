from django.urls import reverse
from swapper import load_model

from openwisp_controller.connection import settings as conn_settings
from openwisp_controller.connection.tests.test_admin import (
    TestCommandInlines as BaseTestCommandInlines,
)
from openwisp_controller.connection.tests.test_admin import (
    TestConnectionAdmin as BaseTestConnectionAdmin,
)
from openwisp_controller.connection.tests.test_api import (
    TestConnectionApi as BaseTestConnectionApi,
)
from openwisp_controller.connection.tests.test_models import (
    TestModels as BaseTestModels,
)
from openwisp_controller.connection.tests.test_models import (
    TestModelsTransaction as BaseTestModelsTransaction,
)
from openwisp_controller.connection.tests.test_notifications import (
    TestNotifications as BaseTestNotifications,
)
from openwisp_controller.connection.tests.test_notifications import (
    TestNotificationTransaction as BaseTestNotificationTransaction,
)
from openwisp_controller.connection.tests.test_ssh import TestSsh as BaseTestSsh
from openwisp_controller.connection.tests.test_tasks import TestTasks as BaseTestTasks


class TestConnectionAdmin(BaseTestConnectionAdmin):
    config_app_label = "config"
    app_label = "sample_connection"


class TestCommandInlines(BaseTestCommandInlines):
    config_app_label = "config"


class TestModels(BaseTestModels):
    app_label = "sample_connection"


class TestModelsTransaction(BaseTestModelsTransaction):
    app_label = "sample_connection"


class TestTasks(BaseTestTasks):
    pass


class TestSsh(BaseTestSsh):
    pass


Notification = load_model("openwisp_notifications", "Notification")


class TestNotifications(BaseTestNotifications):
    app_label = "sample_connection"
    config_app_label = "config"


class TestNotificationTransaction(BaseTestNotificationTransaction):
    app_label = "sample_connection"
    config_app_label = "config"


class TestConnectionApi(BaseTestConnectionApi):
    def test_post_deviceconnection_list(self):
        d1 = self._create_device()
        self._create_config(device=d1)
        path = reverse("connection_api:deviceconnection_list", args=(d1.pk,))
        data = {
            "credentials": self._get_credentials().pk,
            "update_strategy": conn_settings.UPDATE_STRATEGIES[0][0],
            "enabled": True,
            "failure_reason": "",
        }
        with self.assertNumQueries(13):
            response = self.client.post(path, data, content_type="application/json")
        self.assertEqual(response.status_code, 201)


del BaseTestCommandInlines
del BaseTestConnectionAdmin
del BaseTestModels
del BaseTestModelsTransaction
del BaseTestSsh
del BaseTestTasks
del BaseTestNotifications
del BaseTestNotificationTransaction
del BaseTestConnectionApi
