import re

from django.db import migrations


NOTE = "Bed Springs verified six-game H/AB/G totals v26 2026-10-01"

GAME_ROWS = {
    "landmark_2": {
        "jacob": (1, 2), "ethan": (1, 2), "marcus": (1, 2), "wynn": (0, 0),
        "jeff": (1, 2), "jr": (1, 2), "elijah": (2, 2), "shaw": (2, 2),
        "zack": (0, 2), "huddy": (0, 2), "russ": (0, 1), "jordan": (0, 0),
        "scott": (0, 0),
    },
    "landmark_1": {
        "jacob": (3, 4), "ethan": (3, 4), "marcus": (3, 4), "wynn": (3, 4),
        "jeff": (4, 4), "jr": (2, 4), "elijah": (2, 4), "shaw": (2, 4),
        "zack": (3, 4), "huddy": (1, 3), "russ": (2, 3), "jordan": (0, 0),
        "scott": (0, 0),
    },
    "hope_hull": {
        "jacob": (2, 4), "ethan": (3, 4), "marcus": (4, 4), "wynn": (4, 4),
        "jeff": (2, 4), "jr": (0, 0), "elijah": (3, 4), "shaw": (1, 3),
        "zack": (3, 3), "huddy": (0, 3), "russ": (2, 3), "jordan": (3, 3),
        "scott": (1, 3),
    },
    "vaughn_forest": {
        "jacob": (4, 4), "ethan": (3, 4), "marcus": (1, 4), "wynn": (3, 4),
        "jeff": (1, 4), "jr": (0, 0), "elijah": (3, 3), "shaw": (1, 3),
        "zack": (2, 3), "huddy": (2, 3), "russ": (2, 3), "jordan": (2, 3),
        "scott": (1, 3),
    },
    "fraser": {
        "jacob": (3, 4), "ethan": (4, 4), "marcus": (3, 4), "wynn": (4, 4),
        "jeff": (4, 4), "jr": (0, 0), "elijah": (2, 2), "shaw": (3, 3),
        "zack": (2, 3), "huddy": (2, 3), "russ": (1, 3), "jordan": (4, 4),
        "scott": (0, 0),
    },
    "freedom": {
        "jacob": (2, 4), "ethan": (2, 4), "marcus": (3, 4), "wynn": (3, 4),
        "jeff": (3, 4), "jr": (0, 0), "elijah": (2, 2), "shaw": (1, 3),
        "zack": (1, 3), "huddy": (1, 3), "russ": (1, 3), "jordan": (2, 4),
        "scott": (0, 0),
    },
}

PLAYER_MATCHES = {
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

DEFAULT_SCOPE = {
    "landmark_2": "TOURNAMENT",
    "landmark_1": "TOURNAMENT",
    "hope_hull": "LEAGUE",
    "vaughn_forest": "LEAGUE",
    "fraser": "LEAGUE",
    "freedom": "LEAGUE",
}


def norm(value):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).split())


def find_player(players, key):
    aliases = PLAYER_MATCHES[key]
    for player in players:
        if norm(player.display_name) in aliases:
            return player
    for player in players:
        name = norm(player.display_name)
        if any(alias and (name.startswith(alias + " ") or alias in name.split()) for alias in aliases):
            return player
    return None


def scope_for_game(key, games):
    candidates = []
    if key.startswith("landmark"):
        candidates = [game for game in games if "landmark" in norm(game.opponent_name)]
        candidates.sort(key=lambda game: (game.start_at, game.id))
        if key == "landmark_1" and candidates:
            game = candidates[0]
        elif key == "landmark_2" and len(candidates) >= 2:
            game = candidates[1]
        else:
            game = None
    elif key == "hope_hull":
        game = next((g for g in games if "hope hull" in norm(g.opponent_name)), None)
    elif key == "vaughn_forest":
        game = next((g for g in games if "vaughn" in norm(g.opponent_name) and "forest" in norm(g.opponent_name)), None)
    elif key == "fraser":
        game = next((g for g in games if "fraser" in norm(g.opponent_name)), None)
    elif key == "freedom":
        game = next((g for g in games if "freedom" in norm(g.opponent_name)), None)
    else:
        game = None

    if game and str(game.game_type or "").upper() in ("LEAGUE", "TOURNAMENT"):
        return str(game.game_type).upper()
    return DEFAULT_SCOPE[key]


def current_totals(PlateAppearance, Ledger, team_id, player_id, scope):
    appearances = PlateAppearance.objects.filter(
        game__team_id=team_id,
        game__game_type=scope,
        player_id=player_id,
    ).exclude(game__status="CANCELLED")

    game_ids = set(appearances.values_list("game_id", flat=True))
    hits = appearances.filter(result__in=("1B", "2B", "3B", "HR")).count()
    ab = appearances.exclude(result__in=("BB", "SF")).count()
    games = len(game_ids)

    for row in Ledger.objects.filter(team_id=team_id, player_id=player_id, scope=scope):
        hits += int(row.hits or 0)
        ab += int(row.ab or 0)
        games += int(row.games or 0)

    return {"games": games, "hits": hits, "ab": ab}


def apply_verified_totals(apps, schema_editor):
    SportsTeam = apps.get_model("platform_sports", "SportsTeam")
    SportsPlayer = apps.get_model("platform_sports", "SportsPlayer")
    SportsGame = apps.get_model("platform_sports", "SportsGame")
    PlateAppearance = apps.get_model("platform_sports", "SoftballPlateAppearance")
    Ledger = apps.get_model("platform_sports", "SoftballStatLedgerEntry")

    team = (
        SportsTeam.objects.filter(group_id=1)
        .filter(group__name__icontains="bed")
        .filter(group__name__icontains="spring")
        .first()
    )
    if not team or not getattr(team, "created_by_id", None):
        print("Bed Springs v26 stat correction skipped: team or creator not found.")
        return

    games = list(
        SportsGame.objects.filter(team_id=team.id)
        .exclude(status="CANCELLED")
        .order_by("start_at", "id")
    )
    scope_map = {key: scope_for_game(key, games) for key in GAME_ROWS}

    target = {}
    for game_key, rows in GAME_ROWS.items():
        scope = scope_map[game_key]
        for player_key, (hits, ab) in rows.items():
            bucket = target.setdefault((player_key, scope), {"games": 0, "hits": 0, "ab": 0})
            bucket["hits"] += int(hits)
            bucket["ab"] += int(ab)
            if int(hits) > 0 or int(ab) > 0:
                bucket["games"] += 1

    players = list(
        SportsPlayer.objects.filter(
            team_id=team.id,
            merged_into__isnull=True,
            is_active=True,
        ).order_by("id")
    )

    created = 0
    for (player_key, scope), wanted in target.items():
        player = find_player(players, player_key)
        if not player:
            print(f"Bed Springs v26 stat correction: player '{player_key}' not found; skipped.")
            continue

        current = current_totals(PlateAppearance, Ledger, team.id, player.id, scope)
        delta = {
            "games": int(wanted["games"]) - int(current["games"]),
            "hits": int(wanted["hits"]) - int(current["hits"]),
            "ab": int(wanted["ab"]) - int(current["ab"]),
        }
        if not any(delta.values()):
            continue

        Ledger.objects.create(
            team_id=team.id,
            player_id=player.id,
            season_name=(team.season_name or "2026")[:120],
            scope=scope,
            games=delta["games"],
            pa=0,
            ab=delta["ab"],
            hits=delta["hits"],
            doubles=0,
            triples=0,
            home_runs=0,
            walks=0,
            sac_flies=0,
            rbi=0,
            runs=0,
            source="CORRECTION",
            note=NOTE,
            created_by_id=team.created_by_id,
        )
        created += 1

    print(
        "Bed Springs v26 verified H/AB/G correction applied "
        f"to {created} player/scope rows. Scope map: {scope_map}"
    )


def reverse_verified_totals(apps, schema_editor):
    Ledger = apps.get_model("platform_sports", "SoftballStatLedgerEntry")
    Ledger.objects.filter(note=NOTE, source="CORRECTION").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("platform_sports", "0024_bed_springs_verified_hit_ab_totals"),
    ]

    operations = [
        migrations.RunPython(apply_verified_totals, reverse_verified_totals),
    ]
