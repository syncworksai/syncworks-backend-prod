from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("platform_social", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="socialevent",
            name="recurrence_rule",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="socialevent",
            name="weather_dependent",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="socialevent",
            name="weather_note",
            field=models.CharField(blank=True, max_length=240),
        ),
    ]
