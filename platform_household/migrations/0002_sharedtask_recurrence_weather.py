from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("platform_household", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="sharedtask",
            name="recurrence",
            field=models.CharField(choices=[("NONE", "Does not repeat"), ("DAILY", "Daily"), ("WEEKLY", "Weekly"), ("MONTHLY", "Monthly")], default="NONE", max_length=10),
        ),
        migrations.AddField(
            model_name="sharedtask",
            name="recurrence_interval",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="sharedtask",
            name="weather_dependent",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="sharedtask",
            name="weather_note",
            field=models.CharField(blank=True, max_length=240),
        ),
        migrations.AddField(
            model_name="sharedtask",
            name="weather_status",
            field=models.CharField(choices=[("NOT_CHECKED", "Not checked"), ("CLEAR", "Weather clear"), ("WATCH", "Weather watch"), ("BLOCKED", "Weather blocked")], default="NOT_CHECKED", max_length=16),
        ),
        migrations.AlterField(
            model_name="sharedtask",
            name="status",
            field=models.CharField(choices=[("OPEN", "Open"), ("IN_PROGRESS", "In progress"), ("DONE", "Done"), ("SKIPPED", "Skipped"), ("WEATHER_HOLD", "Weather hold")], default="OPEN", max_length=20),
        ),
    ]
