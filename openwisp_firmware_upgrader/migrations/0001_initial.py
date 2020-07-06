from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import model_utils.fields
import openwisp_users.mixins
import uuid
import swapper
from ..swapper import get_model_name

from ..hardware import FIRMWARE_IMAGE_TYPE_CHOICES


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('config', '0015_default_groups_permissions'),
        ('openwisp_users', '0004_default_groups'),
        swapper.dependency('firmware_upgrader', 'Category'),
        swapper.dependency('firmware_upgrader', 'Build'),
        swapper.dependency('firmware_upgrader', 'FirmwareImage'),
        swapper.dependency('firmware_upgrader', 'DeviceFirmware'),
        swapper.dependency('firmware_upgrader', 'BatchUpgradeOperation'),
        swapper.dependency('firmware_upgrader', 'UpgradeOperation'),
    ]

    operations = [
        migrations.CreateModel(
            name='BatchUpgradeOperation',
            fields=[
                (
                    'id',
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    'created',
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name='created',
                    ),
                ),
                (
                    'modified',
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name='modified',
                    ),
                ),
                (
                    'status',
                    models.CharField(
                        choices=[
                            ('in-progress', 'in progress'),
                            ('success', 'completed successfully'),
                            ('failed', 'completed with some failures'),
                        ],
                        default='in-progress',
                        max_length=12,
                    ),
                ),
            ],
            options={
                'swappable': swapper.swappable_setting(
                    'firmware_upgrader', 'BatchUpgradeOperation'
                ),
                'verbose_name_plural': 'Mass upgrade operations',
                'verbose_name': 'Mass upgrade operation',
            },
        ),
        migrations.CreateModel(
            name='Build',
            fields=[
                (
                    'id',
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    'created',
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name='created',
                    ),
                ),
                (
                    'modified',
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name='modified',
                    ),
                ),
                ('version', models.CharField(db_index=True, max_length=32)),
                (
                    'changelog',
                    models.TextField(
                        blank=True,
                        help_text='descriptive text indicating what has changed since the previous version, if applicable',
                        verbose_name='change log',
                    ),
                ),
            ],
            options={
                'swappable': swapper.swappable_setting('firmware_upgrader', 'Build'),
                'ordering': ('-created',),
                'verbose_name': 'Firmware Build',
                'verbose_name_plural': 'Firmware Builds',
            },
        ),
        migrations.CreateModel(
            name='Category',
            fields=[
                (
                    'id',
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    'created',
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name='created',
                    ),
                ),
                (
                    'modified',
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name='modified',
                    ),
                ),
                ('name', models.CharField(db_index=True, max_length=64)),
                ('description', models.TextField(blank=True)),
                (
                    'organization',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to=swapper.get_model_name('openwisp_users', 'Organization'),
                        verbose_name='organization',
                    ),
                ),
            ],
            options={
                'swappable': swapper.swappable_setting('firmware_upgrader', 'Category'),
                'verbose_name': 'Firmware Category',
                'verbose_name_plural': 'Firmware Categories',
            },
            bases=(openwisp_users.mixins.ValidateOrgMixin, models.Model),
        ),
        migrations.CreateModel(
            name='DeviceFirmware',
            fields=[
                (
                    'id',
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    'created',
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name='created',
                    ),
                ),
                (
                    'modified',
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name='modified',
                    ),
                ),
                ('installed', models.BooleanField(default=False)),
                (
                    'device',
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        to=swapper.get_model_name('config', 'Device'),
                    ),
                ),
            ],
            options={
                'swappable': swapper.swappable_setting(
                    'firmware_upgrader', 'DeviceFirmware'
                ),
                'abstract': False,
                'verbose_name': 'Device Firmware',
            },
        ),
        migrations.CreateModel(
            name='FirmwareImage',
            fields=[
                (
                    'id',
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    'created',
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name='created',
                    ),
                ),
                (
                    'modified',
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name='modified',
                    ),
                ),
                ('file', models.FileField(upload_to='')),
                (
                    'type',
                    models.CharField(
                        blank=True,
                        choices=FIRMWARE_IMAGE_TYPE_CHOICES,
                        help_text='firmware image type: model or architecture. Leave blank to attempt determining automatically',
                        max_length=128,
                    ),
                ),
                (
                    'build',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to=get_model_name('Build'),
                    ),
                ),
            ],
            options={
                'swappable': swapper.swappable_setting(
                    'firmware_upgrader', 'FirmwareImage'
                ),
                'abstract': False,
                'verbose_name': 'Firmware Image',
                'verbose_name_plural': 'Firmware Images',
            },
        ),
        migrations.CreateModel(
            name='UpgradeOperation',
            fields=[
                (
                    'id',
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    'created',
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name='created',
                    ),
                ),
                (
                    'modified',
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name='modified',
                    ),
                ),
                (
                    'status',
                    models.CharField(
                        choices=[
                            ('in-progress', 'in progress'),
                            ('success', 'success'),
                            ('failed', 'failed'),
                            ('aborted', 'aborted'),
                        ],
                        default='in-progress',
                        max_length=12,
                    ),
                ),
                ('log', models.TextField(blank=True)),
                (
                    'batch',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        to=swapper.get_model_name(
                            'firmware_upgrader', 'BatchUpgradeOperation'
                        ),
                    ),
                ),
                (
                    'device',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to=swapper.get_model_name('config', 'Device'),
                    ),
                ),
                (
                    'image',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to=get_model_name('FirmwareImage'),
                    ),
                ),
            ],
            options={
                'swappable': swapper.swappable_setting(
                    'firmware_upgrader', 'UpgradeOperation'
                ),
                'abstract': False,
            },
        ),
        migrations.AddField(
            model_name='devicefirmware',
            name='image',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to=get_model_name('FirmwareImage'),
            ),
        ),
        migrations.AddField(
            model_name='build',
            name='category',
            field=models.ForeignKey(
                help_text='if you have different firmware types eg: (BGP routers, wifi APs, DSL gateways) create a category for each.',
                on_delete=django.db.models.deletion.CASCADE,
                to=get_model_name('Category'),
                verbose_name='firmware category',
            ),
        ),
        migrations.AddField(
            model_name='batchupgradeoperation',
            name='build',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE, to=get_model_name('Build'),
            ),
        ),
        migrations.AlterUniqueTogether(
            name='firmwareimage', unique_together={('build', 'type')},
        ),
        migrations.AlterUniqueTogether(
            name='category', unique_together={('name', 'organization')},
        ),
        migrations.AlterUniqueTogether(
            name='build', unique_together={('category', 'version')},
        ),
    ]
