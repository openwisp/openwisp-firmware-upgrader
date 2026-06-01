import logging
import random
from datetime import timedelta
from decimal import Decimal
from functools import partial
from pathlib import Path

import jsonschema
import swapper
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.validators import MaxValueValidator
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from openwisp_notifications.signals import notify
from private_storage.fields import PrivateFileField

from openwisp_controller.connection.exceptions import NoWorkingDeviceConnectionError
from openwisp_users.mixins import ShareableOrgMixin
from openwisp_utils.base import TimeStampedEditableModel

from .. import settings as app_settings
from ..exceptions import (
    FirmwareUpgradeOptionsException,
    ReconnectionFailed,
    RecoverableFailure,
    UpgradeAborted,
    UpgradeCancelled,
    UpgradeNotNeeded,
)
from ..hardware import (
    FIRMWARE_IMAGE_MAP,
    FIRMWARE_IMAGE_TYPE_CHOICES,
    REVERSE_FIRMWARE_IMAGE_MAP,
)
from ..signals import firmware_upgrader_log_updated
from ..swapper import get_model_name, load_model
from ..tasks import (
    batch_upgrade_operation,
    create_all_device_firmwares,
    create_device_firmware,
    retry_pending_upgrade,
    upgrade_firmware,
)
from ..utils import (
    UpgradeProgress,
    get_upgrader_class_for_device,
    get_upgrader_class_from_device_connection,
    get_upgrader_schema_for_device,
)

logger = logging.getLogger(__name__)
PROGRESS_MIN = 0
PROGRESS_MAX = 100


class UpgradeOptionsMixin(models.Model):
    upgrade_options = models.JSONField(default=dict, blank=True)

    class Meta:
        abstract = True

    def validate_upgrade_options(self):
        if not self.upgrade_options:
            return
        try:
            upgrader_class = self.upgrader_class
        except ObjectDoesNotExist:
            raise ValidationError(
                _("No related connection or credentials found for this device.")
            )
        if not getattr(upgrader_class, "SCHEMA"):
            raise ValidationError(
                _("Using upgrade options is not allowed with this upgrader.")
            )
        try:
            upgrader_class.validate_upgrade_options(self.upgrade_options)
        except jsonschema.ValidationError:
            raise ValidationError("The upgrade options are invalid")
        except FirmwareUpgradeOptionsException as error:
            raise ValidationError(*error.args)

    def clean(self):
        super().clean()
        self.validate_upgrade_options()


class AbstractCategory(ShareableOrgMixin, TimeStampedEditableModel):
    name = models.CharField(max_length=64, db_index=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name

    class Meta:
        abstract = True
        verbose_name = _("Firmware Category")
        verbose_name_plural = _("Firmware Categories")
        unique_together = ("name", "organization")


class AbstractBuild(TimeStampedEditableModel):
    category = models.ForeignKey(
        get_model_name("Category"),
        on_delete=models.CASCADE,
        verbose_name=_("firmware category"),
        help_text=_(
            "if you have different firmware types "
            "eg: (BGP routers, wifi APs, DSL gateways) "
            "create a category for each."
        ),
    )
    version = models.CharField(max_length=32, db_index=True)
    os = models.CharField(
        _("OS identifier"),
        max_length=64,
        blank=True,
        null=True,
        help_text=_(
            "OS identifier as presented by the device, "
            "used to automatically recognize the firmware "
            "image used by new devices that register "
            "into the system"
        ),
    )
    changelog = models.TextField(
        _("change log"),
        blank=True,
        help_text=_(
            "descriptive text indicating what "
            "has changed since the previous "
            "version, if applicable"
        ),
    )

    class Meta:
        abstract = True
        verbose_name = _("Firmware Build")
        verbose_name_plural = _("Firmware Builds")
        unique_together = ("category", "version")
        ordering = ("-created",)

    def __str__(self):
        try:
            return f"{self.category} v{self.version}"
        except ObjectDoesNotExist:
            return super().__str__()

    def clean(self):
        # Make sure that ('category__organization', 'os') is unique too
        try:
            category = self.category
        except ObjectDoesNotExist:
            return
        if not self.os:
            return
        if (
            load_model("Build")
            .objects.filter(category__organization=category.organization, os=self.os)
            .exclude(pk=self.pk)
            .exists()
        ):
            raise ValidationError(
                {
                    "os": _(
                        f'A build with this OS identifier ("{self.os}") and '
                        f'organization ("{category.organization}") already exists'
                    )
                }
            )

    def batch_upgrade(
        self, firmwareless, upgrade_options=None, group=None, location=None
    ):
        upgrade_options = upgrade_options or {}
        # Check if there are any devices to upgrade with the given filters
        dry_run_result = load_model("BatchUpgradeOperation").dry_run(
            build=self, group=group, location=location
        )
        # If no devices match the filters, don't start the upgrade
        if not (
            dry_run_result["device_firmwares"].exists()
            or (firmwareless and dry_run_result["devices"].exists())
        ):
            raise ValidationError(
                _(
                    "No devices found matching the specified filters. "
                    "Please adjust your group and/or location filters."
                )
            )
        batch = load_model("BatchUpgradeOperation")(
            build=self, upgrade_options=upgrade_options, group=group, location=location
        )
        batch.full_clean()
        batch.save()
        transaction.on_commit(
            partial(batch_upgrade_operation.delay, batch.pk, firmwareless)
        )
        return batch

    def _find_related_device_firmwares(
        self, select_devices=False, group=None, location=None
    ):
        """
        Returns all the DeviceFirmware objects related to the firmware
        category of this build that have not been installed yet
        """
        related = ["image"]
        if select_devices:
            related.append("device")
        qs = (
            load_model("DeviceFirmware")
            .objects.all()
            .select_related(*related)
            .filter(image__build__category_id=self.category_id)
            .exclude(image__build=self, installed=True)
            .order_by("-created")
        )
        if group:
            qs = qs.filter(device__group=group)
        if location:
            qs = qs.filter(device__devicelocation__location=location)
        return qs

    def _find_firmwareless_devices(self, boards=None, group=None, location=None):
        """
        Returns devices which have no related DeviceFirmware
        but that are upgradable to one of the image of this build
        """
        if boards is None:
            boards = []
            for image in self.firmwareimage_set.all():
                boards += image.boards
        Device = swapper.load_model("config", "Device")
        qs = Device.objects.filter(
            devicefirmware__isnull=True,
            model__in=boards,
        )
        if self.category.organization_id:
            qs = qs.filter(organization_id=self.category.organization_id)
        if group:
            qs = qs.filter(group=group)
        if location:
            qs = qs.filter(devicelocation__location=location)
        return qs.order_by("-created")


def get_build_directory(instance, filename):
    build_pk = str(instance.build.pk)
    return "/".join([build_pk, filename])


class AbstractFirmwareImage(TimeStampedEditableModel):
    build = models.ForeignKey(get_model_name("Build"), on_delete=models.CASCADE)
    file = PrivateFileField(
        "File",
        upload_to=get_build_directory,
        max_file_size=app_settings.MAX_FILE_SIZE,
        storage=app_settings.PRIVATE_STORAGE_INSTANCE,
        max_length=255,
    )
    type = models.CharField(
        blank=True,
        max_length=128,
        choices=FIRMWARE_IMAGE_TYPE_CHOICES,
        help_text=_(
            "firmware image type: model or "
            "architecture. Leave blank to attempt "
            "determining automatically"
        ),
    )

    class Meta:
        abstract = True
        verbose_name = _("Firmware Image")
        verbose_name_plural = _("Firmware Images")
        unique_together = ("build", "type")

    def __str__(self):
        if hasattr(self, "build") and self.type:
            return f"{self.build}: {self.get_type_display()}"
        return super().__str__()

    @property
    def boards(self):
        return FIRMWARE_IMAGE_MAP[self.type]["boards"]

    def clean(self):
        self._clean_type()
        try:
            self.boards
        except KeyError:
            raise ValidationError({"type": "Could not find boards for this type"})

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        self._remove_file(self.file.name)

    @classmethod
    def _remove_file(cls, file_path):
        """
        Deletes a file and cleans up its parent directory if empty.
        Handles corner cases gracefully and logs accordingly.
        """
        storage = cls.file.field.storage
        try:
            storage.delete(file_path)
            logger.info("Deleted firmware file: %s", file_path)
        except Exception as e:
            logger.error("Error deleting firmware file %s: %s", file_path, str(e))
            return False
        # Delete the directory if empty
        try:
            dir_path = str(Path(file_path).parent)
            if not dir or dir_path == ".":
                return True
            dirs, files = storage.listdir(dir_path)
            if dirs or files:
                logger.debug("Directory %s is not empty, skipping deletion", dir_path)
                return True
            storage.delete(dir_path)
        except FileNotFoundError:
            logger.debug("Directory %s already removed", dir_path)
        except Exception as error:
            logger.error("Could not delete directory %s: %s", dir_path, str(error))
        else:
            logger.info("Deleted empty directory: %s", dir_path)
        return True

    def _clean_type(self):
        """
        auto determine type if missing
        """
        if self.type:
            return
        filename = self.file.name
        # removes leading prefix
        self.type = "-".join(filename.split("-")[1:])

    @classmethod
    def build_pre_delete_handler(cls, sender, instance, **kwargs):
        """
        Triggers deletion of firmware image files when a Build is deleted.
        """
        cls.schedule_firmware_file_deletion(build=instance)

    @classmethod
    def category_pre_delete_handler(cls, sender, instance, **kwargs):
        """
        Triggers deletion of firmware image files when a Category is deleted.
        """
        cls.schedule_firmware_file_deletion(build__category=instance)

    @classmethod
    def organization_pre_delete_handler(cls, sender, instance, **kwargs):
        """
        Triggers deletion of firmware image files when an Organization is deleted.
        """
        cls.schedule_firmware_file_deletion(build__category__organization=instance)

    @classmethod
    def schedule_firmware_file_deletion(cls, **filter_kwargs):
        """
        Schedules the deletion of firmware image files in the background.

        Args:
            **filter_kwargs: Django ORM filter arguments
        """
        # Avoid circular import
        from ..tasks import delete_firmware_files

        files_to_delete = []
        # Get all firmware images matching the filter criteria
        queryset = cls.objects.filter(**filter_kwargs)
        for image in queryset.iterator():
            if image.file and image.file.name:
                files_to_delete.append(image.file.name)
        if files_to_delete:
            # Schedule file deletion after transaction is committed
            transaction.on_commit(partial(delete_firmware_files.delay, files_to_delete))


class AbstractDeviceFirmware(TimeStampedEditableModel):
    device = models.OneToOneField(
        swapper.get_model_name("config", "Device"), on_delete=models.CASCADE
    )
    image = models.ForeignKey(get_model_name("FirmwareImage"), on_delete=models.CASCADE)
    installed = models.BooleanField(default=False)
    _old_image = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._update_old_image()

    class Meta:
        verbose_name = _("Device Firmware")
        abstract = True

    def clean(self):
        if not hasattr(self, "image") or not hasattr(self, "device"):
            return
        if (
            self.image.build.category.organization is not None
            and self.image.build.category.organization != self.device.organization
        ):
            raise ValidationError(
                {
                    "image": _(
                        "The organization of the image doesn't "
                        "match the organization of the device"
                    )
                }
            )
        # When an admin adds credentials and changes the firmware image in the
        # same save, the new credentials haven't been persisted yet at the time
        # this check runs, so without `_skip_connection_check` the form would
        # wrongly reject the change with "please add credentials".
        # `DeviceFirmwareForm` sets the flag when it sees credentials in the
        # submitted data.
        skip_connection_check = getattr(self, "_skip_connection_check", False)
        will_start_upgrade = self.image_has_changed or not self.installed
        if (
            will_start_upgrade
            and not skip_connection_check
            and self.device.deviceconnection_set.count() < 1
        ):
            raise ValidationError(
                _(
                    "This device does not have a related connection object defined "
                    "yet and therefore it would not be possible to upgrade it, "
                    'please add one in the section named "Credentials"'
                )
            )
        if self.device.model not in self.image.boards:
            raise ValidationError(_("Device model and image model do not match"))

    @property
    def image_has_changed(self):
        return self._state.adding or self.image_id != self._old_image.id

    def save(self, batch=None, upgrade=True, upgrade_options=None, *args, **kwargs):
        # if firwmare image has changed launch upgrade
        # upgrade won't be launched the first time
        if upgrade and (self.image_has_changed or not self.installed):
            self.installed = False
            super().save(*args, **kwargs)
            self.create_upgrade_operation(batch, upgrade_options=upgrade_options or {})
        else:
            super().save(*args, **kwargs)
        self._update_old_image()

    def _update_old_image(self):
        if hasattr(self, "image"):
            self._old_image = self.image

    def create_upgrade_operation(self, batch, upgrade_options=None):
        uo_model = load_model("UpgradeOperation")
        operation = uo_model(
            device=self.device, image=self.image, upgrade_options=upgrade_options
        )
        if batch:
            operation.batch = batch
            operation.is_persistent = batch.is_persistent
        operation.full_clean()
        operation.save()
        # launch ``upgrade_firmware`` in the background (celery)
        # once changes are committed to the database
        transaction.on_commit(partial(upgrade_firmware.delay, operation.pk))
        return operation

    @classmethod
    def create_for_device(cls, device, firmware_image=None):
        """
        Creates a ``DeviceFirmware`` instance for the specified device
        If ``firmware_image`` is not supplied, it will be tried
        to be determined automatically.

        May return ``None`` if it was not possible to create the DeviceFirmware.
        """
        DeviceFirmware = load_model("DeviceFirmware")
        FirmwareImage = load_model("FirmwareImage")
        image_type = REVERSE_FIRMWARE_IMAGE_MAP.get(device.model)

        if not image_type:
            return

        if not firmware_image:
            try:
                firmware_image = FirmwareImage.objects.get(
                    build__category__organization_id=device.organization_id,
                    build__os=device.os,
                    type=image_type,
                )
            except FirmwareImage.DoesNotExist:
                return

        device_fw = DeviceFirmware(device=device, image=firmware_image, installed=True)
        try:
            device_fw.full_clean()
        except ValidationError as e:
            logger.warning(e)
            return
        device_fw.save(upgrade=False)
        return device_fw

    @classmethod
    def auto_add_device_firmware_to_device(cls, instance, created, **kwargs):
        # Automatically associate DeviceFirmware to the registered Device
        if not created:
            return
        if not instance.device.os or not instance.device.model:
            return
        if instance.device.model not in REVERSE_FIRMWARE_IMAGE_MAP:
            return

        transaction.on_commit(partial(create_device_firmware.delay, instance.device.pk))

    @classmethod
    def auto_create_device_firmwares(cls, instance, created, **kwargs):
        if created:
            transaction.on_commit(
                partial(create_all_device_firmwares.delay, instance.pk)
            )

    @classmethod
    def get_image_queryset_for_device(cls, device, device_firmware=None):
        FirmwareImage = cls.image.field.related_model
        qs = (
            FirmwareImage.objects.filter(
                Q(build__category__organization_id=device.organization_id)
                | Q(build__category__organization__isnull=True)
            )
            .order_by("-created")
            .select_related("build", "build__category")
        )
        # if device model is defined
        # restrict the images to the ones compatible with it
        if device.model and device.model in REVERSE_FIRMWARE_IMAGE_MAP:
            qs = qs.filter(type=REVERSE_FIRMWARE_IMAGE_MAP[device.model])
        # if DeviceFirmware instance already exists
        # restrict images to the ones of the same category
        if device_firmware and hasattr(device_firmware, "image"):
            qs = qs.filter(build__category_id=device_firmware.image.build.category_id)
        return qs


class AbstractBatchUpgradeOperation(UpgradeOptionsMixin, TimeStampedEditableModel):
    build = models.ForeignKey(get_model_name("Build"), on_delete=models.CASCADE)
    group = models.ForeignKey(
        swapper.get_model_name("config", "DeviceGroup"),
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        verbose_name=_("device group"),
    )
    location = models.ForeignKey(
        swapper.get_model_name("geo", "Location"),
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        verbose_name=_("location"),
    )
    STATUS_CHOICES = (
        ("idle", _("idle")),
        ("in-progress", _("in progress")),
        ("success", _("completed successfully")),
        ("failed", _("completed with some failures")),
        ("cancelled", _("completed with some cancellations")),
    )
    status = models.CharField(
        max_length=12, choices=STATUS_CHOICES, default=STATUS_CHOICES[0][0]
    )
    is_persistent = models.BooleanField(
        default=True,
        verbose_name=_("persistent"),
        help_text=_(
            "if enabled, the mass upgrade keeps retrying "
            "offline devices until they come back online "
            "or the operation is cancelled"
        ),
    )
    last_reminder_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("last reminder at"),
        help_text=_(
            "timestamp of the last pending-upgrade reminder fired for "
            "this batch, null if no reminder has been sent yet"
        ),
    )

    class Meta:
        abstract = True
        verbose_name = _("Mass upgrade operation")
        verbose_name_plural = _("Mass upgrade operations")

    def __str__(self):
        return f"{self.build} ({timezone.localtime(self.created).strftime('%Y-%m-%d %H:%M:%S')})"

    def clean(self):
        super().clean()
        if (
            self.group
            and self.build.category.organization
            and self.group.organization != self.build.category.organization
        ):
            raise ValidationError(
                {
                    "group": _(
                        "The organization of the group doesn't match "
                        "the organization of the build category"
                    )
                }
            )
        if (
            self.location
            and self.build.category.organization
            and self.location.organization != self.build.category.organization
        ):
            raise ValidationError(
                {
                    "location": _(
                        "The organization of the location doesn't match "
                        "the organization of the build category"
                    )
                }
            )
        self._validate_is_persistent_immutable()

    def _validate_is_persistent_immutable(self):
        """
        Reject changes to ``is_persistent`` once the batch has left ``idle``.
        Idle batches haven't dispatched anything yet, so the flag can still
        flip; after that the retry pipeline relies on it staying stable.
        """
        if self._state.adding:
            return
        stored_status, stored_is_persistent = (
            load_model("BatchUpgradeOperation")
            .objects.values_list("status", "is_persistent")
            .get(pk=self.pk)
        )
        if stored_status == "idle":
            return
        if self.is_persistent != stored_is_persistent:
            raise ValidationError(
                {
                    "is_persistent": _(
                        "Persistent cannot be changed after the mass "
                        "upgrade has started"
                    )
                }
            )

    def upgrade(self, firmwareless):
        self.status = "in-progress"
        self.save()
        self.upgrade_related_devices()
        if firmwareless:
            self.upgrade_firmwareless_devices()

    @staticmethod
    def dry_run(build, group=None, location=None):
        related_device_fw = build._find_related_device_firmwares(
            select_devices=True, group=group, location=location
        )
        firmwareless_devices = build._find_firmwareless_devices(
            group=group, location=location
        )
        return {
            "device_firmwares": related_device_fw,
            "devices": firmwareless_devices,
        }

    def upgrade_related_devices(self):
        """
        upgrades all devices which have an
        existing related DeviceFirmware
        """
        device_firmwares = self.build._find_related_device_firmwares(
            group=self.group, location=self.location
        )
        for device_fw in device_firmwares:
            image = self.build.firmwareimage_set.filter(
                type=device_fw.image.type
            ).first()
            if image:
                device_fw.image = image
                device_fw.full_clean()
                device_fw.save(self, upgrade_options=self.upgrade_options)

    def upgrade_firmwareless_devices(self):
        """
        upgrades all devices which do not
        have a related DeviceFirmware yet
        (referred as "firmwareless")
        """
        # for each image, find related "firmwareless"
        # devices and perform upgrade one by one
        for image in self.build.firmwareimage_set.all():
            devices = self.build._find_firmwareless_devices(
                image.boards, group=self.group, location=self.location
            )
            for device in devices:
                DeviceFirmware = load_model("DeviceFirmware")
                device_fw = DeviceFirmware(device=device, image=image)
                device_fw.full_clean()
                device_fw.save(self, upgrade_options=self.upgrade_options)

    @cached_property
    def upgrade_operations(self):
        return self.upgradeoperation_set.all()

    @cached_property
    def total_operations(self):
        return self.upgrade_operations.count()

    @property
    def organization_id(self):
        return self.build.category.organization_id

    @property
    def pending_count(self):
        return self.upgrade_operations.filter(status="pending").count()

    @property
    def progress_report(self):
        stats = self.upgrade_operations.aggregate(
            completed=models.Count(
                "id", filter=~models.Q(status__in=("in-progress", "pending"))
            ),
            pending=models.Count("id", filter=models.Q(status="pending")),
        )
        if stats["pending"]:
            return _(f"{stats['completed']} complete, {stats['pending']} pending")
        return _(f"{stats['completed']} out of {self.total_operations}")

    @property
    def success_rate(self):
        if not self.total_operations:
            return 0
        success = self.upgrade_operations.filter(status="success").count()
        return self.__get_rate(success)

    @property
    def failed_rate(self):
        if not self.total_operations:
            return 0
        failed = self.upgrade_operations.filter(status="failed").count()
        return self.__get_rate(failed)

    @property
    def aborted_rate(self):
        if not self.total_operations:
            return 0
        aborted = self.upgrade_operations.filter(status="aborted").count()
        return self.__get_rate(aborted)

    @property
    def cancelled_rate(self):
        if not self.total_operations:
            return 0
        cancelled = self.upgrade_operations.filter(status="cancelled").count()
        return self.__get_rate(cancelled)

    @property
    def upgrader_class(self):
        return self._get_upgrader_class()

    @property
    def upgrader_schema(self):
        return self._get_upgrader_schema()

    def _get_upgrader_class(self, related_device_fw=None, firmwareless_devices=None):
        if self.upgrade_operations:
            return get_upgrader_class_for_device(self.upgrade_operations[0].device)
        related_device_fw = (
            related_device_fw
            or self.build._find_related_device_firmwares(select_devices=True)
        )
        if related_device_fw:
            return get_upgrader_class_for_device(related_device_fw.first().device)
        firmwareless_devices = (
            firmwareless_devices or self.build._find_firmwareless_devices()
        )
        if firmwareless_devices:
            return get_upgrader_class_for_device(firmwareless_devices.first())

    def _get_upgrader_schema(self, related_device_fw=None, firmwareless_devices=None):
        upgrader_class = self._get_upgrader_class(
            related_device_fw, firmwareless_devices
        )
        return getattr(upgrader_class, "SCHEMA", None)

    def __get_rate(self, number):
        result = Decimal(number) / Decimal(self.total_operations) * 100
        return round(result, 2)

    def calculate_and_update_status(self):
        """
        Calculate batch status based on operation statuses and update if changed.
        This method consolidates all business logic for determining batch status.
        Returns tuple of (status, stats_dict) for WebSocket publishing.

        Status determination rules:
        - 'in-progress': If any operation is still in progress or pending
        - 'cancelled': If completed and any operation was cancelled
        - 'failed': If completed and any operation failed or aborted
        - 'success': If all operations completed successfully
        - Otherwise: Maintain current status
        """
        operations = self.upgradeoperation_set
        stats = operations.aggregate(
            total_operations=models.Count("id"),
            in_progress=models.Count(
                models.Case(
                    models.When(status="in-progress", then=1),
                    output_field=models.IntegerField(),
                )
            ),
            pending=models.Count(
                models.Case(
                    models.When(status="pending", then=1),
                    output_field=models.IntegerField(),
                )
            ),
            completed=models.Count(
                models.Case(
                    models.When(
                        ~models.Q(status__in=("in-progress", "pending")), then=1
                    ),
                    output_field=models.IntegerField(),
                )
            ),
            successful=models.Count(
                models.Case(
                    models.When(status="success", then=1),
                    output_field=models.IntegerField(),
                )
            ),
            failed=models.Count(
                models.Case(
                    models.When(status="failed", then=1),
                    output_field=models.IntegerField(),
                )
            ),
            cancelled=models.Count(
                models.Case(
                    models.When(status="cancelled", then=1),
                    output_field=models.IntegerField(),
                )
            ),
            aborted=models.Count(
                models.Case(
                    models.When(status="aborted", then=1),
                    output_field=models.IntegerField(),
                )
            ),
        )
        # Determine overall batch status based on individual operation statuses
        if stats["in_progress"] > 0 or stats["pending"] > 0:
            new_status = "in-progress"
        elif stats["failed"] > 0 or stats["aborted"] > 0:
            new_status = "failed"
        elif stats["cancelled"] > 0:
            new_status = "cancelled"
        elif (
            stats["successful"] > 0
            and stats["completed"] == stats["total_operations"]
            and stats["total_operations"] > 0
        ):
            new_status = "success"
        else:
            new_status = self.status
        # Update status only if it has changed
        if self.status != new_status:
            self.status = new_status
            self.save(update_fields=["status"])
        return new_status, stats


class AbstractUpgradeOperation(UpgradeOptionsMixin, TimeStampedEditableModel):

    CANCELLABLE_STATUS = ("in-progress", "pending")
    STATUS_CHOICES = (
        ("in-progress", _("in progress")),
        ("success", _("success")),
        ("failed", _("failed")),  # failed at late stage or can't reconnect
        ("cancelled", _("cancelled")),  # cancelled by the user
        ("aborted", _("aborted")),  # aborted due to prerequisites not met
        ("pending", _("pending")),  # offline device; waiting for periodic retry
    )
    device = models.ForeignKey(
        swapper.get_model_name("config", "Device"), on_delete=models.CASCADE
    )
    image = models.ForeignKey(
        get_model_name("FirmwareImage"), null=True, on_delete=models.SET_NULL
    )
    status = models.CharField(
        max_length=12, choices=STATUS_CHOICES, default=STATUS_CHOICES[0][0]
    )
    log = models.TextField(blank=True)
    progress = models.PositiveSmallIntegerField(
        default=PROGRESS_MIN,
        validators=[
            MaxValueValidator(PROGRESS_MAX),
        ],
    )
    batch = models.ForeignKey(
        get_model_name("BatchUpgradeOperation"),
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )
    is_persistent = models.BooleanField(
        default=False,
        verbose_name=_("persistent"),
        help_text=_(
            "if enabled, the operation stays pending and retries "
            "when the device comes back online"
        ),
    )
    retry_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_("retry count"),
        help_text=_(
            "number of times the operation has gone from in-progress to pending"
        ),
    )
    next_retry_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("next retry at"),
        help_text=_(
            "when the periodic scanner should next retry this "
            "pending operation, null if no retry is queued"
        ),
    )

    def clean(self):
        super().clean()
        self._validate_is_persistent_immutable()

    def _validate_is_persistent_immutable(self):
        """
        Reject changes to ``is_persistent`` after the operation is saved.
        Flipping it on an existing row would orphan a pending retry chain
        or silently re-arm a finished operation.
        """
        if self._state.adding:
            return
        stored_is_persistent = (
            load_model("UpgradeOperation")
            .objects.values_list("is_persistent", flat=True)
            .get(pk=self.pk)
        )
        if self.is_persistent != stored_is_persistent:
            raise ValidationError(
                {
                    "is_persistent": _(
                        "Persistent cannot be changed after the "
                        "upgrade operation has been saved"
                    )
                }
            )

    def __str__(self):
        return f"{self.device} ({timezone.localtime(self.created).strftime('%Y-%m-%d %H:%M:%S')})"

    class Meta:
        abstract = True

    def log_line(self, line, save=True):
        if self.log:
            self.log += f"\n{line}"
        else:
            self.log = line
        logger.info(f"# {line}")
        if save:
            self.save()
            firmware_upgrader_log_updated.send(
                sender=self.__class__, instance=self, line=line
            )

    def update_progress(self, progress, save=True):
        """Update progress with validation."""
        if not isinstance(progress, (int, float)):
            raise ValidationError(
                _("Progress must be numeric, got %(progress_type)s")
                % {"progress_type": type(progress)}
            )
        if not PROGRESS_MIN <= progress <= PROGRESS_MAX:
            raise ValidationError(
                _("Progress must be between %(min)s-%(max)s, got %(progress)s")
                % {"min": PROGRESS_MIN, "max": PROGRESS_MAX, "progress": progress}
            )
        self.progress = int(progress)
        if save:
            self.save()

    def cancel(self):
        """Cancels the upgrade operation if conditions are met, atomically."""
        with transaction.atomic():
            # A concurrent upgrade worker can change status/progress
            # between fetch and save(), so cancellation can succeed
            # or fail incorrectly.
            # By using an UPDATE query, we avoid such situation.
            updated = self._meta.model.objects.filter(
                pk=self.pk,
                status__in=self.CANCELLABLE_STATUS,
                progress__lt=UpgradeProgress.CANCELLATION_THRESHOLD,
            ).update(status="cancelled")
            if not updated:
                # The cancellation did not succeed, check why
                self.refresh_from_db(fields=["status", "progress"])
                if self.status not in self.CANCELLABLE_STATUS:
                    raise ValueError(
                        _("Cannot cancel operation with status: %(status)s")
                        % {"status": self.status}
                    )
                if self.progress >= UpgradeProgress.CANCELLATION_THRESHOLD:
                    raise ValueError(
                        _(
                            "Cannot cancel upgrade: firmware reflashing has already started"
                        )
                    )
                raise ValueError(_("Unknown error during cancellation"))
            # Since we use update() to change the status, we need to refresh
            # the instance for 2 reasons:
            # 1. get the updated status
            # 2. get any log ling which may have been written
            #    concurrently in background workers, so we avoid overwriting
            self.refresh_from_db()
            self.log_line(_("Upgrade operation has been cancelled by user"))

    def _calculate_next_retry(self):
        options = app_settings.PERSISTENT_RETRY_OPTIONS
        exponent = max(self.retry_count - 1, 0)
        delay = min(
            options["base_delay"] * (options["multiplier"] ** exponent),
            options["max_delay"],
        )
        jitter = options["jitter"]
        jittered = delay * random.uniform(1 - jitter, 1 + jitter)
        return timezone.now() + timedelta(seconds=jittered)

    @classmethod
    def handle_health_status_changed(cls, sender, instance, status, **kwargs):
        """
        Dispatches retries for pending upgrades when device health recovers.
        """
        if status != "ok":
            return
        pending_pks = list(
            cls.objects.filter(device=instance.device, status="pending").values_list(
                "pk", flat=True
            )
        )
        if not pending_pks:
            return
        jitter = app_settings.PERSISTENT_RETRY_OPTIONS["signal_jitter"]
        for pk in pending_pks:
            retry_pending_upgrade.apply_async(
                args=[pk], countdown=random.uniform(0, jitter)
            )

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        if "status" in field_names:
            instance._previous_status = instance.status
        return instance

    @classmethod
    def notify_on_failed_persistent_upgrade(cls, sender, instance, created, **kwargs):
        """
        Fires a notification when a persistent upgrade transitions to failed.
        """
        if created or not instance.is_persistent:
            return
        if instance.status != "failed":
            return
        if getattr(instance, "_previous_status", None) == "failed":
            return
        notify.send(
            sender=instance,
            type="generic_message",
            target=instance.device,
            level="error",
            description=_("Persistent upgrade for device %(device)s failed.")
            % {"device": instance.device},
        )
        instance._previous_status = instance.status

    def _recoverable_failure_handler(self, recoverable, error):
        cause = str(error)
        if recoverable:
            self.log_line(f"Detected a recoverable failure: {cause}.\n", save=False)
            self.log_line("The upgrade operation will be retried soon.")
            raise error
        if self.is_persistent and isinstance(error, RecoverableFailure):
            self.status = "pending"
            self.retry_count += 1
            self.next_retry_at = self._calculate_next_retry()
            self.log_line(
                f"All immediate retries exhausted: {cause}. "
                f"Scheduled persistent retry #{self.retry_count} "
                f"at {self.next_retry_at}.",
                save=False,
            )
            return
        self.status = "failed"
        self.log_line(f"Max retries exceeded. Upgrade failed: {cause}.", save=False)

    def upgrade(self, recoverable=True):
        # Do not run if operation is not in-progress (eg: cancelled, aborted, success, failed)
        if self.status != "in-progress":
            return
        DeviceConnection = swapper.load_model("connection", "DeviceConnection")
        try:
            conn = DeviceConnection.get_working_connection(self.device)
        except NoWorkingDeviceConnectionError as error:
            if error.connection is None:
                self.log_line("No device connection available")
                return

            log_template = (
                "Failed to connect with {device} using {credentials}."
                " Error: {failure_reason}"
            )
            for conn in self.device.deviceconnection_set.select_related("credentials"):
                self.log_line(
                    log_template.format(
                        device=self.device.name,
                        credentials=conn.credentials,
                        failure_reason=conn.failure_reason,
                    ),
                    save=False,
                )
            self._recoverable_failure_handler(
                recoverable,
                RecoverableFailure(
                    (
                        "Failed to establish connection with the device,"
                        " tried all DeviceConnections"
                    )
                ),
            )
            self.save()
            return
        installed = False
        # prevent multiple upgrade operations for
        # the same device running at the same time
        qs = (
            load_model("UpgradeOperation")
            .objects.filter(device=self.device, status__in=("in-progress", "pending"))
            .exclude(pk=self.pk)
        )
        if qs.exists():
            message = _("Another upgrade operation is in progress, aborting...")
            logger.warning(message)
            self.log_line(message, save=False)
            self.status = "aborted"
            self.save()
            return
        upgrader_class = get_upgrader_class_from_device_connection(conn)
        if not upgrader_class:
            return
        upgrader = upgrader_class(self, conn)
        try:
            upgrader.upgrade(self.image.file)
        # this exception is raised when the checksum present in the device
        # equals the checksum of the image we are trying to flash, which
        # means the device was aleady flashed previously with the same image
        except UpgradeNotNeeded:
            self.status = "success"
            self.update_progress(100, save=False)
            installed = True
        # this exception is raised when the test of the image fails,
        # meaning the image file is corrupted or not apt for flashing
        except UpgradeAborted:
            self.status = "aborted"
        # this exception is raised when the upgrade is cancelled by the user
        except UpgradeCancelled:
            self.status = "cancelled"
        # raising this exception will cause celery to retry again
        # the upgrade according to its configuration
        except RecoverableFailure as e:
            self._recoverable_failure_handler(recoverable, e)
        # failure to reconnect to the device after reflashing or any
        # other unexpected exception will flag the upgrade as failed
        except (Exception, ReconnectionFailed) as e:
            cause = str(e)
            self.log_line(cause)
            self.status = "failed"
            # if the reconnection failed we'll add some more info
            if isinstance(e, ReconnectionFailed):
                # update device connection info
                conn.is_working = False
                conn.failure_reason = cause
                conn.last_attempt = timezone.now()
                conn.save()
                # even if the reconnection failed,
                # the firmware image has been flashed
                installed = True
        # if no exception has been raised, the upgrade was successful
        else:
            installed = True
            self.status = "success"
            self.update_progress(100, save=False)
        self.save()
        # if the firmware has been successfully installed,
        # or if it was already installed
        # set `instaleld` to `True` on the devicefirmware instance
        if installed:
            self.device.devicefirmware.installed = True
            self.device.devicefirmware.save(upgrade=False)

    def validate_upgrade_options(self):
        """Validate options only for new upgrade operations.

        Pre-existing upgrade operations are readonly, but validation of relationship
        can become complex and generate a lot of edge cases, in order to keep things
        simple this validation step is skipped for pre-existing objects.
        """
        try:
            super().validate_upgrade_options()
        except ValidationError:
            if self._state.adding:
                raise

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # when an operation is completed
        # trigger an update on the batch operation
        if self.batch and self.status != "in-progress":
            self.batch.calculate_and_update_status()

    @property
    def upgrader_schema(self):
        return get_upgrader_schema_for_device(self.device)

    @property
    def upgrader_class(self):
        return get_upgrader_class_for_device(self.device)
