from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("platform_sports", "0011_gamecast_controls"),
    ]

    operations = [
        migrations.AddField(
            model_name="sportsplayer",
            name="merged_into",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="merged_player_records", to="platform_sports.sportsplayer"),
        ),
        migrations.AddField(
            model_name="sportsgame",
            name="fan_gamecast_notified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
