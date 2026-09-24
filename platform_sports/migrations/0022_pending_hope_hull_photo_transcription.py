"""Keep ambiguous handwriting out of official season stats until approved.

The second user-provided week-two sheet matches Hope Hull's five inning run
totals (6, 3, 3, 5, 3). Rows below are review suggestions only. They neither
create PlateAppearances nor claim any RBI, run scored, or verified hit.
"""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


# (batting order, inning, proposed result, margin note)
HOPE_HULL_SHEET = (
    (1, 1, "1B", "Circled 1B; confirm player run/RBI."),
    (1, 2, "OUT", "F-marked flyout; check fielder and out number."),
    (1, 5, "OUT", "F8-like flyout; check fielder."),
    (2, 1, "1B", "Circled 1B."),
    (2, 2, "1B", "Circled 1B; confirm mark."),
    (2, 3, "FC", "FC notation; confirm whether an out was recorded."),
    (2, 5, "1B", "Circled 1B."),
    (3, 1, "HR", "HR circle appears marked; confirm against original image."),
    (3, 2, "1B", "Hit diamond; confirm hit type."),
    (3, 4, "1B", "Circled 1B/diamond; confirm."),
    (3, 5, "HR", "HR circle appears marked; confirm against original image."),
    (4, 1, "1B", "Circled 1B."),
    (4, 2, "2B", "Circled 2B."),
    (4, 4, "1B", "Circled 1B."),
    (4, 5, "1B", "Circled 1B."),
    (5, 1, "OUT", "G3 groundout."),
    (5, 2, "OUT", "F9 flyout."),
    (5, 4, "", "Extra-base/hit notation unclear; choose correct result."),
    (5, 5, "", "Hit/walk notation unclear; choose correct result."),
    (6, 1, "3B", "Circled 3B."),
    (6, 2, "", "Notation unclear; check original."),
    (6, 3, "2B", "Circled 2B."),
    (6, 4, "BB", "Circled BB."),
    (6, 5, "OUT", "G5-4 groundout/force; confirm."),
    (7, 1, "1B", "Circled 1B."),
    (7, 3, "2B", "Circled 2B."),
    (7, 4, "", "E-1/FC notation; confirm hit versus error/choice."),
    (8, 1, "OUT", "G6-5 marked groundout."),
    (8, 3, "OUT", "G4 marked groundout."),
    (8, 4, "1B", "Circled 1B."),
    (9, 1, "1B", "Circled 1B."),
    (9, 3, "BB", "Circled BB."),
    (9, 4, "1B", "Circled 1B."),
    (10, 1, "OUT", "F3 flyout."),
    (10, 3, "OUT", "F6 flyout."),
    (10, 4, "OUT", "F7 flyout."),
    (11, 2, "1B", "Circled 1B."),
    (11, 3, "1B", "Circled 1B, check handwriting."),
    (11, 4, "OUT", "F7 flyout."),
    (12, 2, "OUT", "G3 groundout."),
    (12, 3, "1B", "Circled 1B."),
    (12, 5, "OUT", "G6 groundout."),
)


def seed_hope_hull_review_candidates(apps, schema_editor):
    Game = apps.get_model("platform_sports", "SportsGame")
    Inning = apps.get_model("platform_sports", "SportsGameInning")
    Lineup = apps.get_model("platform_sports", "SportsLineupSpot")
    Candidate = apps.get_model("platform_sports", "SportsGameBookCandidate")
    matches = list(Game.objects.filter(
        team__group__name="Bed Springs Baptist",
        opponent_name="Hope Hull Church", runs_for=20, runs_against=12,
        status="FINAL",
    )[:2])
    if len(matches) != 1:
        return
    game = matches[0]
    if dict(Inning.objects.filter(game=game).values_list("inning", "team_runs")) != {
        1: 6, 2: 3, 3: 3, 4: 5, 5: 3,
    }:
        return
    lineup = dict(Lineup.objects.filter(game=game).values_list("batting_order", "player_id"))
    if len(lineup) != 12 or game.plate_appearances.exists():
        return
    source_label = "IMG_2334.jpeg / Hope Hull / submitted 2026-09-24"
    for order, inning, result, note in HOPE_HULL_SHEET:
        Candidate.objects.get_or_create(
            game=game, source_label=source_label,
            player_id=lineup[order], inning=inning, source_slot=1,
            defaults={
                "result": result,
                "outs_recorded": 1 if result == "OUT" else (
                    0 if result in ("1B", "2B", "3B", "HR", "BB") else None
                ),
                "confidence": "UNCERTAIN" if not result else "REVIEW",
                "transcription_note": note,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("platform_sports", "0021_finalize_hope_hull_from_scorebook"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="SportsGameBookCandidate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_label", models.CharField(max_length=100)),
                ("inning", models.PositiveSmallIntegerField()),
                ("source_slot", models.PositiveSmallIntegerField(default=1)),
                ("result", models.CharField(blank=True, choices=[
                    ("1B","Single"),("2B","Double"),("3B","Triple"),("HR","Home run"),
                    ("BB","Walk"),("OUT","Out"),("K","Strikeout"),("ROE","Reached on error"),
                    ("FC","Fielder's choice"),("SF","Sacrifice fly"),
                ], max_length=4)),
                ("outs_recorded", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("rbi", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("runs_scored", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("confidence", models.CharField(choices=[
                    ("CLEAR","Clear notation"),("REVIEW","Review handwriting"),("UNCERTAIN","Uncertain"),
                ], default="REVIEW", max_length=10)),
                ("transcription_note", models.CharField(blank=True, max_length=240)),
                ("status", models.CharField(choices=[
                    ("PENDING","Needs verification"),("APPROVED","Approved"),("REJECTED","Rejected"),
                ], default="PENDING", max_length=10)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("game", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="book_candidates", to="platform_sports.sportsgame")),
                ("player", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="book_candidates", to="platform_sports.sportsplayer")),
                ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="scorebook_candidates_reviewed", to=settings.AUTH_USER_MODEL)),
                ("verified_appearance", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="source_candidate", to="platform_sports.softballplateappearance")),
            ],
            options={"ordering": ("game_id","inning","player_id","source_slot","id")},
        ),
        migrations.AddConstraint(
            model_name="sportsgamebookcandidate",
            constraint=models.UniqueConstraint(
                fields=("game","source_label","player","inning","source_slot"),
                name="sports_unique_book_draft_mark",
            ),
        ),
        migrations.RunPython(seed_hope_hull_review_candidates, migrations.RunPython.noop),
    ]
