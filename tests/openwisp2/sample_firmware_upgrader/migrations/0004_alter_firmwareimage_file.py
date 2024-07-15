# Generated by Django 4.2.13 on 2024-05-30 07:51

from urllib.parse import urljoin
from openwisp_firmware_upgrader.settings import FIRMWARE_API_BASEURL, IMAGE_URL_PATH
from django.db import migrations
import openwisp_firmware_upgrader.base.models
import private_storage.fields
import private_storage.storage.files


class Migration(migrations.Migration):

    dependencies = [
        ("sample_firmware_upgrader", "0003_create_device_firmware"),
    ]

    operations = [
        migrations.AlterField(
            model_name="firmwareimage",
            name="file",
            field=private_storage.fields.PrivateFileField(
                max_length=255,
                storage=private_storage.storage.files.PrivateFileSystemStorage(
                    base_url=urljoin(FIRMWARE_API_BASEURL, IMAGE_URL_PATH),
                ),
                upload_to=openwisp_firmware_upgrader.base.models.get_build_directory,
                verbose_name="File",
            ),
        ),
    ]
