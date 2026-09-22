from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("platform_sports_analytics", "0001_initial"),
    ]

    operations = [
        migrations.AddField(model_name="gamecastshare", name="show_live_score", field=models.BooleanField(default=True)),
        migrations.AddField(model_name="gamecastshare", name="show_current_batter", field=models.BooleanField(default=True)),
        migrations.AddField(model_name="gamecastshare", name="show_lineup", field=models.BooleanField(default=True)),
        migrations.AddField(model_name="gamecastshare", name="show_recent_plays", field=models.BooleanField(default=True)),
        migrations.AddField(model_name="gamecastshare", name="allow_follow", field=models.BooleanField(default=True)),
    ]
