from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("platform_sports", "0019_link_verified_bed_springs_accounts"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(model_name="softballplateappearance", name="outs_before", field=models.PositiveSmallIntegerField(blank=True, null=True)),
        migrations.AddField(model_name="softballplateappearance", name="base_state", field=models.CharField(blank=True, default="", max_length=8)),
        migrations.AddField(model_name="softballplateappearance", name="situation_objective", field=models.CharField(blank=True, default="", max_length=24)),
        migrations.AddField(model_name="softballplateappearance", name="runners_advanced", field=models.PositiveSmallIntegerField(default=0)),
        migrations.AddField(model_name="softballplateappearance", name="situation_success", field=models.BooleanField(blank=True, null=True)),
        migrations.CreateModel(
            name="SportsPracticeSession",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("BP","Batting practice"),("SITUATIONS","Situations"),("FIELDING","Fielding"),("TRAINING","Training")], default="BP", max_length=16)),
                ("practiced_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("title", models.CharField(blank=True, max_length=120)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sports_practice_sessions_created", to=settings.AUTH_USER_MODEL)),
                ("player", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="practice_sessions", to="platform_sports.sportsplayer")),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="practice_sessions", to="platform_sports.sportsteam")),
            ],
            options={"ordering": ("-practiced_at","-id")},
        ),
        migrations.CreateModel(
            name="SportsPracticeRep",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sequence", models.PositiveIntegerField()),
                ("outs_before", models.PositiveSmallIntegerField(default=0)),
                ("base_state", models.CharField(blank=True, default="", max_length=8)),
                ("objective", models.CharField(choices=[("QUALITY_AB","Quality at-bat"),("ADVANCE_RUNNER","Move the runner"),("SAC_FLY","Sacrifice fly"),("SCORE_RUNNER","Score the runner"),("TWO_OUT_HIT","Two-out hitting"),("HIT_BEHIND_RUNNER","Hit behind runner")], default="QUALITY_AB", max_length=24)),
                ("result", models.CharField(choices=[("1B","Single"),("2B","Double"),("3B","Triple"),("HR","Home run"),("BB","Walk"),("OUT","Out"),("K","Strikeout"),("ROE","Reached on error"),("FC","Fielder's choice"),("SF","Sacrifice fly")], max_length=4)),
                ("runners_advanced", models.PositiveSmallIntegerField(default=0)),
                ("rbi", models.PositiveSmallIntegerField(default=0)),
                ("successful", models.BooleanField(default=False)),
                ("notes", models.CharField(blank=True, max_length=240)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("session", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="reps", to="platform_sports.sportspracticesession")),
            ],
            options={"ordering": ("sequence","id")},
        ),
        migrations.AddIndex(model_name="sportspracticesession", index=models.Index(fields=["team","practiced_at"], name="sports_practice_team_date")),
        migrations.AddIndex(model_name="sportspracticesession", index=models.Index(fields=["player","practiced_at"], name="sports_practice_player_date")),
        migrations.AddIndex(model_name="sportspracticerep", index=models.Index(fields=["session","objective"], name="sports_practice_rep_obj")),
        migrations.AddConstraint(model_name="sportspracticerep", constraint=models.UniqueConstraint(fields=("session","sequence"), name="sports_unique_practice_rep_seq")),
    ]
