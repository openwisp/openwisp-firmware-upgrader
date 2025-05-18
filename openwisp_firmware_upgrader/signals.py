import logging

from django.db import transaction

from .tasks import delete_firmware_files

logger = logging.getLogger(__name__)


def _collect_firmware_files(firmware_images):
    """
    Collects file paths from firmware images that need to be deleted
    """
    paths = []
    for image in firmware_images:
        if image.file:
            paths.append(image.file.name)
    return paths


def delete_build_files(sender, instance, **kwargs):
    """
    Delete firmware files when a Build is deleted
    """
    logger.info(f"Build delete signal received for build {instance.pk}")
    firmware_images = instance.firmwareimage_set.all()
    logger.info(f"Found {firmware_images.count()} firmware images to delete")
    paths = _collect_firmware_files(firmware_images)
    logger.info(f"Collected file paths: {paths}")
    if paths:
        logger.info("Scheduling delete_firmware_files task")

        def schedule_delete_task():
            delete_firmware_files.delay(paths)

        transaction.on_commit(schedule_delete_task)


def delete_category_files(sender, instance, **kwargs):
    """
    Delete firmware files when a Category is deleted
    """
    logger.info(f"Category delete signal received for category {instance.pk}")
    firmware_images = []
    builds = instance.build_set.all()
    logger.info(f"Found {builds.count()} builds to process")
    for build in builds:
        images = build.firmwareimage_set.all()
        logger.info(f"Found {images.count()} firmware images in build {build.pk}")
        firmware_images.extend(images)
    paths = _collect_firmware_files(firmware_images)
    logger.info(f"Collected file paths: {paths}")
    if paths:
        logger.info("Scheduling delete_firmware_files task")

        def schedule_delete_task():
            delete_firmware_files.delay(paths)

        transaction.on_commit(schedule_delete_task)


def delete_organization_files(sender, instance, **kwargs):
    """
    Delete firmware files when an Organization is deleted
    """
    logger.info(f"Organization delete signal received for organization {instance.pk}")
    firmware_images = []
    categories = instance.category_set.all()
    logger.info(f"Found {categories.count()} categories to process")
    for category in categories:
        builds = category.build_set.all()
        logger.info(f"Found {builds.count()} builds in category {category.pk}")
        for build in builds:
            images = build.firmwareimage_set.all()
            logger.info(f"Found {images.count()} firmware images in build {build.pk}")
            firmware_images.extend(images)
    paths = _collect_firmware_files(firmware_images)
    logger.info(f"Collected file paths: {paths}")
    if paths:
        logger.info("Scheduling delete_firmware_files task")

        def schedule_delete_task():
            delete_firmware_files.delay(paths)

        transaction.on_commit(schedule_delete_task)
