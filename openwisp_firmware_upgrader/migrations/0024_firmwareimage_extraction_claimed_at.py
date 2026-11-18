from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("firmware_upgrader", "0023_backfill_board_from_hardware_map"),
    ]
    operations = [
        migrations.AddField(
            model_name="firmwareimage",
            name="extraction_claimed_at",
            field=models.DateTimeField(
                blank=True, null=True, verbose_name="extraction claimed at"
            ),
        ),
    ]
