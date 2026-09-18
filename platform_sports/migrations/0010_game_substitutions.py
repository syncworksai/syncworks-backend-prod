from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("platform_sports", "0009_player_account_invites"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SportsSubstitution",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("batting_order", models.PositiveSmallIntegerField()),
                ("defensive_position", models.CharField(blank=True, max_length=40)),
                ("inning", models.PositiveSmallIntegerField(default=1)),
                ("note", models.CharField(blank=True, max_length=180)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="sports_substitutions_created", to=settings.AUTH_USER_MODEL)),
                ("game", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="substitutions", to="platform_sports.sportsgame")),
                ("incoming_player", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="substitutions_in", to="platform_sports.sportsplayer")),
                ("outgoing_player", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="substitutions_out", to="platform_sports.sportsplayer")),
            ],
            options={"ordering": ("created_at", "id")},
        ),
        migrations.AddIndex(
            model_name="sportssubstitution",
            index=models.Index(fields=["game", "batting_order"], name="sports_sub_game_order"),
        ),
    ]
