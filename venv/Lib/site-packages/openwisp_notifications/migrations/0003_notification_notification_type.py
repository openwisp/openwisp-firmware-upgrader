from django.db import migrations, models

from openwisp_notifications.types import NOTIFICATION_CHOICES


class Migration(migrations.Migration):
    dependencies = [
        ('openwisp_notifications', '0002_default_permissions'),
    ]

    operations = [
        migrations.AddField(
            model_name='notification',
            name='type',
            field=models.CharField(
                choices=NOTIFICATION_CHOICES,
                max_length=30,
                null=True,
            ),
        ),
    ]
