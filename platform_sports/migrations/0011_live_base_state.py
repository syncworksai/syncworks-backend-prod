from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("platform_sports", "0010_game_substitutions"),
    ]

    operations = [
        migrations.AddField(
            model_name="sportsgame",
            name="runner_on_first",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="sportsgame",
            name="runner_on_second",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="sportsgame",
            name="runner_on_third",
            field=models.BooleanField(default=False),
        ),
    ]
