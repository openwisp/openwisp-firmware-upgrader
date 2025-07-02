import logging

from django.db import models
from django.utils.html import escape
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _
from packaging.version import parse as parse_version

from ..admin_theme.system_info import (
    get_enabled_openwisp_modules,
    get_openwisp_installation_method,
    get_openwisp_version,
    get_os_details,
)
from ..base import TimeStampedEditableModel
from ..utils import retryable_request

logger = logging.getLogger(__name__)


class OpenwispVersion(TimeStampedEditableModel):
    modified = None
    module_version = models.JSONField(default=dict, blank=True)

    COLLECTOR_URL = "https://analytics.openwisp.io/cleaninsights.php"

    class Meta:
        ordering = ("-created",)

    @classmethod
    def log_module_version_changes(cls, current_versions):
        """Logs changes to the version of installed OpenWISP modules.

        Returns a tuple of booleans indicating:

        - whether this is a new installation
        - whether any OpenWISP modules has been upgraded.

        If no module has been upgraded, it won't store anything in the DB.
        """
        openwisp_version = cls.objects.first()
        if not openwisp_version:
            # If no OpenwispVersion object is present,
            # it means that this is a new installation and
            # we don't need to check for upgraded modules.
            cls.objects.create(module_version=current_versions)
            return True, False
        # Check which installed modules have been upgraded by comparing
        # the currently installed versions in current_versions with the
        # versions stored in the OpenwispVersion object. The return value
        # is a dictionary of module:version pairs that have been upgraded.
        old_versions = openwisp_version.module_version
        upgraded_modules = {}
        for module, version in current_versions.items():
            # The OS version does not follow semver,
            # therefore it's handled differently.
            if module in ["kernel_version", "os_version", "hardware_platform"]:
                if old_versions.get(module) != version:
                    upgraded_modules[module] = version
            elif (
                # Check if a new OpenWISP module was enabled
                # on an existing installation
                module not in old_versions
                or (
                    # Check if an OpenWISP module was upgraded
                    module in old_versions
                    and parse_version(old_versions[module]) < parse_version(version)
                )
            ):
                upgraded_modules[module] = version
            openwisp_version.module_version[module] = version
        # Log version changes
        if upgraded_modules:
            OpenwispVersion.objects.create(module_version=current_versions)
            return False, True
        return False, False

    @classmethod
    def send_usage_metrics(cls, category):
        consent_obj = Consent.objects.first()
        if consent_obj and not consent_obj.user_consented:
            return
        assert category in ["Install", "Heartbeat", "Upgrade"]

        current_versions = get_enabled_openwisp_modules()
        current_versions.update({"OpenWISP Version": get_openwisp_version()})
        current_versions.update(get_os_details())
        is_install, is_upgrade = OpenwispVersion.log_module_version_changes(
            current_versions
        )

        # Handle special conditions when the user forgot to execute the migrate
        # command, and an install or upgrade operation is detected in the
        # Heartbeat event. In this situation, we override the category.
        if category == "Heartbeat":
            if is_install:
                category = "Install"
            if is_upgrade:
                category = "Upgrade"
        elif category == "Upgrade" and not is_upgrade:
            # The task was triggered with "Upgrade" category, but no
            # upgrades were detected in the OpenWISP module versions.
            # This occurs when the migrate command is executed but
            # no OpenWISP python module was upgraded.
            # We don't count these as upgrades.
            return
        elif category == "Install" and not is_install:
            # Similar to above, but for "Install" category
            return

        metrics = cls._get_events(category, current_versions)
        metrics.extend(
            cls._get_events(
                category, {"Installation Method": get_openwisp_installation_method()}
            )
        )
        logger.info(f"Sending metrics, category={category}")
        cls._post_metrics(metrics)
        logger.info(f"Metrics sent successfully, category={category}")
        logger.info(f"Metrics: {metrics}")

    @classmethod
    def _post_metrics(cls, events):
        try:
            response = retryable_request(
                "post",
                url=cls.COLLECTOR_URL,
                json={
                    "idsite": 5,
                    "events": events,
                },
                max_retries=10,
            )
            assert response.status_code == 204
        except Exception as error:
            if isinstance(error, AssertionError):
                message = f"HTTP {response.status_code} Response"
            else:
                message = str(error)
            logger.error(
                f"Collection of usage metrics failed, max retries exceeded. Error: {message}"
            )

    @classmethod
    def _get_events(cls, category, data):
        """Returns a list of events that will be sent to CleanInsights.

        This method requires two input parameters, category and data,
        which represent usage metrics, and returns a list of events in a
        format accepted by the Clean Insights Matomo Proxy (CIMP) API.

        Read the "Event Measurement Schema" in the CIMP documentation:
        https://cutt.ly/SwBkC40A
        """
        events = []
        unix_time = int(now().timestamp())
        for key, value in data.items():
            events.append(
                {
                    # OS Details, Install, Hearthbeat, Upgrade
                    "category": category,
                    # Name of OW module or OS parameter
                    "action": escape(key),
                    # Actual version of OW module, OS or general OW version
                    "name": escape(value),
                    # Value is always 1
                    "value": 1,
                    # Event happened only 1 time, we do not aggregate
                    "times": 1,
                    "period_start": unix_time,
                    "period_end": unix_time,
                }
            )
        return events


class Consent(TimeStampedEditableModel):
    """Stores consent to collect anonymous usage metrics.

    The ``shown_once`` field is used to track whether the info message
    about the metric collection has been shown to the superuser on their
    first login. The ``user_consented`` field stores whether the superuser
    has opted-out of collecting anonymous usage metrics.
    """

    shown_once = models.BooleanField(
        default=False,
    )
    # Metric collection is opt-out. By default, metric collection is enabled.
    # Disabling it is a one-time action by the superuser. Whenever a superuser
    # disables metric collection, they are opting-out to share anymore anonymous
    # usage metrics with the OpenWISP project.
    user_consented = models.BooleanField(
        default=True,
        verbose_name=_(
            "Help improve OpenWISP by allowing the "
            "collection of anonymous usage metrics."
        ),
        help_text=_(
            "These statistics help us prioritize features, "
            " fix bugs, and better support real-world usage,"
            " all without collecting any personal data. "
            '<a href="https://openwisp.io/docs/user/usage-metric-collection.html"'
            ' target="_blank">Learn more about why we collect metrics</a>.'
        ),
    )
