# Generated by Django 3.0.5 on 2020-06-02 17:56

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('firmware_upgrader', '0003_private_media'),
    ]

    operations = [
        migrations.AlterField(
            model_name='batchupgradeoperation',
            name='status',
            field=models.CharField(
                choices=[
                    ('idle', 'idle'),
                    ('in-progress', 'in progress'),
                    ('success', 'completed successfully'),
                    ('failed', 'completed with some failures'),
                ],
                default='idle',
                max_length=12,
            ),
        ),
    ]
