import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("platform_sports", "0012_player_merges_fan_gamecast_notice"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="sportsplayerprofile", name="card_photo_data",
            field=models.BinaryField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="sportsplayerprofile", name="card_photo_mime",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
        migrations.AddField(
            model_name="sportsplayerprofile", name="card_nickname",
            field=models.CharField(blank=True, default="", max_length=48),
        ),
        migrations.AddField(
            model_name="sportsplayerprofile", name="card_photo_position",
            field=models.PositiveSmallIntegerField(default=50),
        ),
        migrations.AddField(
            model_name="sportsplayerprofile", name="card_style",
            field=models.CharField(choices=[
                ("CLASSIC", "Classic Gold"), ("NEON", "Neon Night"),
                ("DIAMOND", "Diamond"), ("MIDNIGHT", "Midnight"),
            ], default="CLASSIC", max_length=24),
        ),
        migrations.CreateModel(
            name="SportsPlayerMoment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[
                    ("EXTRA_BASE", "Took an extra base"),
                    ("STEAL", "Successful steal (where permitted)"),
                    ("TYING_HIT", "Late tying hit"),
                    ("GO_AHEAD_HIT", "Late go-ahead hit"),
                ], max_length=24)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("game", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="verified_player_moments", to="platform_sports.sportsgame")),
                ("plate_appearance", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="verified_moments", to="platform_sports.softballplateappearance")),
                ("player", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="verified_moments", to="platform_sports.sportsplayer")),
                ("verified_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sports_moments_verified", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-game__start_at", "-id")},
        ),
        migrations.AddConstraint(
            model_name="sportsplayermoment",
            constraint=models.UniqueConstraint(fields=("game", "player", "kind"), name="sports_one_verified_kind_per_game"),
        ),
        migrations.AddIndex(
            model_name="sportsplayermoment",
            index=models.Index(fields=("player", "kind"), name="sports_moment_player_kind"),
        ),
    ]
