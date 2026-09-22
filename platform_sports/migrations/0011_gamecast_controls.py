import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("platform_sports", "0010_game_substitutions"),
    ]

    operations = [
        migrations.AddField(
            model_name="sportsgame",
            name="gamecast_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="sportsgame",
            name="gamecast_token",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.AddField(
            model_name="sportsgame",
            name="gamecast_show_batter",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="sportsgame",
            name="gamecast_show_recent_plays",
            field=models.BooleanField(default=True),
        ),
    ]
