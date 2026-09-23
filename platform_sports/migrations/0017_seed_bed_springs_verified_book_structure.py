"""Seed verified historical Bed Springs lineups and inning totals from paper books.

Only data that is unambiguous on the source sheets is applied here. Individual
plate appearances remain untouched until a coach verifies each handwritten result.
"""
from datetime import datetime, timezone as utc

from django.db import migrations


GAMES = (
    {
        "opponent": "Frazer Church",
        "kickoff": datetime(2026, 9, 16, 0, 30, tzinfo=utc.utc),
        "innings": ((1, 7), (2, 6), (3, 11), (4, 3)),
        "lineup": (
            ("Jacob Lord", 1),
            ("Ethan Headley", 2),
            ("Marcus Hardy", 3),
            ("James Wynn", 4),
            ("Jeff Davis", 5),
            ("Elijah Headley", 6),
            ("Jordan Bray", 7),
            ("Shaw Aplin", 8),
            ("Zack Azar", 9),
            ("Josh Hudson", 10),
            ("Russ Browning", 11),
        ),
    },
    {
        "opponent": "Hope Hull Church",
        "kickoff": datetime(2026, 9, 23, 0, 30, tzinfo=utc.utc),
        "innings": ((1, 6), (2, 3), (3, 3), (4, 5), (5, 3)),
        "lineup": (
            ("Jacob Lord", 1),
            ("Ethan Headley", 2),
            ("Marcus Hardy", 3),
            ("James Wynn", 4),
            ("Jeff Davis", 5),
            ("Elijah Headley", 6),
            ("Jordan Bray", 7),
            ("Shaw Aplin", 8),
            ("Zack Azar", 9),
            ("Josh Hudson", 10),
            ("Russ Browning", 11),
            ("Scott Rayburn", 12),
        ),
    },
)


def seed_books(apps, schema_editor):
    SportsGame = apps.get_model("platform_sports", "SportsGame")
    SportsGameInning = apps.get_model("platform_sports", "SportsGameInning")
    SportsLineupSpot = apps.get_model("platform_sports", "SportsLineupSpot")
    SportsPlayer = apps.get_model("platform_sports", "SportsPlayer")

    for source in GAMES:
        matches = list(
            SportsGame.objects.filter(
                team__group__name="Bed Springs Baptist",
                team__sport="SOFTBALL",
                opponent_name=source["opponent"],
                start_at=source["kickoff"],
            )[:2]
        )
        if len(matches) != 1:
            continue
        game = matches[0]

        # Never rewrite a game that has already received verified play-by-play.
        if game.plate_appearances.exists():
            continue

        if not SportsLineupSpot.objects.filter(game=game).exists():
            names = [name for name, _ in source["lineup"]]
            players = {
                player.display_name: player
                for player in SportsPlayer.objects.filter(team=game.team, display_name__in=names)
            }
            if len(players) == len(names):
                SportsLineupSpot.objects.bulk_create([
                    SportsLineupSpot(
                        game=game,
                        player=players[name],
                        batting_order=order,
                        defensive_position="",
                        is_starter=True,
                    )
                    for name, order in source["lineup"]
                ])

        for inning, runs in source["innings"]:
            line, _ = SportsGameInning.objects.get_or_create(
                game=game,
                inning=inning,
                defaults={"team_runs": runs, "opponent_runs": 0, "opponent_hits": 0},
            )
            if line.team_runs == 0:
                line.team_runs = runs
                line.save(update_fields=("team_runs", "updated_at"))


class Migration(migrations.Migration):
    dependencies = [
        ("platform_sports", "0016_confirm_bed_springs_week_two_results"),
    ]

    operations = [
        migrations.RunPython(seed_books, migrations.RunPython.noop),
    ]
