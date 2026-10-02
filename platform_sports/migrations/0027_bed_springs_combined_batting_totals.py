import re

from django.db import migrations


NOTE = "Bed Springs verified combined batting totals 2026-10-01 v27"

# Verified season totals supplied by the manager. "runs" is the source table's
# S / scored column. RBI was intentionally left blank in the source and is not
# changed by this migration.
TARGETS = {
    "jacob":  {"g": 6, "h": 15, "ab": 22, "d": 1, "t": 0, "hr": 0, "bb": 5, "sf": 0, "gidp": 0, "runs": 4},
    "ethan":  {"g": 6, "h": 16, "ab": 22, "d": 1, "t": 0, "hr": 0, "bb": 3, "sf": 0, "gidp": 1, "runs": 6},
    "marcus": {"g": 6, "h": 15, "ab": 22, "d": 1, "t": 0, "hr": 3, "bb": 1, "sf": 0, "gidp": 0, "runs": 4},
    "wynn":   {"g": 5, "h": 17, "ab": 20, "d": 2, "t": 0, "hr": 0, "bb": 0, "sf": 0, "gidp": 0, "runs": 8},
    "jeff":   {"g": 6, "h": 15, "ab": 22, "d": 2, "t": 1, "hr": 1, "bb": 0, "sf": 2, "gidp": 0, "runs": 4},
    "jr":     {"g": 2, "h": 3,  "ab": 6,  "d": 0, "t": 0, "hr": 0, "bb": 0, "sf": 0, "gidp": 1, "runs": 3},
    "elijah": {"g": 6, "h": 14, "ab": 17, "d": 1, "t": 0, "hr": 0, "bb": 1, "sf": 0, "gidp": 0, "runs": 5},
    "shaw":   {"g": 6, "h": 10, "ab": 18, "d": 0, "t": 0, "hr": 0, "bb": 0, "sf": 0, "gidp": 0, "runs": 6},
    "zack":   {"g": 6, "h": 11, "ab": 18, "d": 1, "t": 2, "hr": 0, "bb": 0, "sf": 0, "gidp": 1, "runs": 5},
    "huddy":  {"g": 6, "h": 6,  "ab": 17, "d": 1, "t": 0, "hr": 0, "bb": 0, "sf": 0, "gidp": 1, "runs": 2},
    "russ":   {"g": 6, "h": 8,  "ab": 16, "d": 0, "t": 0, "hr": 0, "bb": 1, "sf": 0, "gidp": 0, "runs": 5},
    "jordan": {"g": 4, "h": 11, "ab": 14, "d": 2, "t": 0, "hr": 0, "bb": 1, "sf": 0, "gidp": 0, "runs": 2},
    "scott":  {"g": 2, "h": 2,  "ab": 6,  "d": 0, "t": 0, "hr": 0, "bb": 1, "sf": 0, "gidp": 0, "runs": 1},
}

ALIASES = {
    "jacob": ("jacob lord", "jake lord", "jake"),
    "ethan": ("ethan headley", "ethan"),
    "marcus": ("marcus hardy", "marcus"),
    "wynn": ("james wynn", "wynn"),
    "jeff": ("jeff davis", "jeff"),
    "jr": ("jr", "j r"),
    "elijah": ("elijah headley", "elijah"),
    "shaw": ("shaw aplin", "shaw"),
    "zack": ("zack azar", "zach azar", "zack", "zach"),
    "huddy": ("josh hudson", "huddy", "hudson"),
    "russ": ("russ browning", "russ"),
    "jordan": ("jordan bray", "jordan"),
    "scott": ("scott", "sott"),
}


def norm(value):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).split())


def find_player(players, key):
    aliases = ALIASES[key]
    for player in players:
        if norm(player.display_name) in aliases:
            return player
    for player in players:
        name = norm(player.display_name)
        if any(alias and (name.startswith(alias + " ") or alias in name.split()) for alias in aliases):
            return player
    return None


def current_combined(PlateAppearance, Ledger, team_id, player_id):
    appearances = PlateAppearance.objects.filter(
        game__team_id=team_id,
        game__game_type__in=("LEAGUE", "TOURNAMENT"),
        player_id=player_id,
    ).exclude(game__status="CANCELLED")

    game_ids = set(appearances.values_list("game_id", flat=True))
    current = {
        "games": len(game_ids),
        "pa": appearances.count(),
        "ab": appearances.exclude(result__in=("BB", "SF")).count(),
        "hits": appearances.filter(result__in=("1B", "2B", "3B", "HR")).count(),
        "doubles": appearances.filter(result="2B").count(),
        "triples": appearances.filter(result="3B").count(),
        "home_runs": appearances.filter(result="HR").count(),
        "walks": appearances.filter(result="BB").count(),
        "sac_flies": appearances.filter(result="SF").count(),
        "double_plays": 0,
        "runs": sum(int(value or 0) for value in appearances.values_list("runs_scored", flat=True)),
    }

    for row in Ledger.objects.filter(
        team_id=team_id,
        player_id=player_id,
        scope__in=("LEAGUE", "TOURNAMENT", "COMBINED"),
    ):
        current["games"] += int(row.games or 0)
        current["pa"] += int(row.pa or 0)
        current["ab"] += int(row.ab or 0)
        current["hits"] += int(row.hits or 0)
        current["doubles"] += int(row.doubles or 0)
        current["triples"] += int(row.triples or 0)
        current["home_runs"] += int(row.home_runs or 0)
        current["walks"] += int(row.walks or 0)
        current["sac_flies"] += int(row.sac_flies or 0)
        current["double_plays"] += int(row.double_plays or 0)
        current["runs"] += int(row.runs or 0)
    return current


def apply_targets(apps, schema_editor):
    SportsTeam = apps.get_model("platform_sports", "SportsTeam")
    SportsPlayer = apps.get_model("platform_sports", "SportsPlayer")
    PlateAppearance = apps.get_model("platform_sports", "SoftballPlateAppearance")
    Ledger = apps.get_model("platform_sports", "SoftballStatLedgerEntry")

    team = (
        SportsTeam.objects.filter(group_id=1)
        .filter(group__name__icontains="bed")
        .filter(group__name__icontains="spring")
        .first()
    )
    if not team or not getattr(team, "created_by_id", None):
        print("Bed Springs v27 combined stat correction skipped: team or creator not found.")
        return

    players = list(
        SportsPlayer.objects.filter(team_id=team.id, merged_into__isnull=True, is_active=True)
        .order_by("id")
    )

    created = 0
    for key, source in TARGETS.items():
        player = find_player(players, key)
        if not player:
            print(f"Bed Springs v27: player '{key}' not found; skipped.")
            continue

        target = {
            "games": source["g"],
            "pa": source["ab"] + source["bb"] + source["sf"],
            "ab": source["ab"],
            "hits": source["h"],
            "doubles": source["d"],
            "triples": source["t"],
            "home_runs": source["hr"],
            "walks": source["bb"],
            "sac_flies": source["sf"],
            "double_plays": source["gidp"],
            "runs": source["runs"],
        }
        current = current_combined(PlateAppearance, Ledger, team.id, player.id)
        delta = {field: int(target[field]) - int(current[field]) for field in target}
        if not any(delta.values()):
            continue

        Ledger.objects.create(
            team_id=team.id,
            player_id=player.id,
            season_name=(team.season_name or "2026")[:120],
            scope="COMBINED",
            games=delta["games"],
            pa=delta["pa"],
            ab=delta["ab"],
            hits=delta["hits"],
            doubles=delta["doubles"],
            triples=delta["triples"],
            home_runs=delta["home_runs"],
            walks=delta["walks"],
            sac_flies=delta["sac_flies"],
            double_plays=delta["double_plays"],
            rbi=0,
            runs=delta["runs"],
            source="CORRECTION",
            note=NOTE,
            created_by_id=team.created_by_id,
        )
        created += 1

    print(f"Bed Springs v27 combined batting targets applied to {created} player rows.")


def reverse_targets(apps, schema_editor):
    Ledger = apps.get_model("platform_sports", "SoftballStatLedgerEntry")
    Ledger.objects.filter(note=NOTE, source="CORRECTION", scope="COMBINED").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("platform_sports", "0026_combined_scope_and_double_plays"),
    ]

    operations = [
        migrations.RunPython(apply_targets, reverse_targets),
    ]
