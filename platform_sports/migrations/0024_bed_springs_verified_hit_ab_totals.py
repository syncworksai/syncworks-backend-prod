import re

from django.db import migrations


NOTE = "Bed Springs verified H/AB totals from 2026-10-01 score sheet"

# User-verified game-by-game hit / at-bat totals.
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
    "jeff": ("jeff",),
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
    aliases = PLAYER_MATCHES[key]
    exact = [p for p in players if norm(p.display_name) in aliases]
    if len(exact) == 1:
        return exact[0]
    contains = []
    for player in players:
        name = norm(player.display_name)
        if any(alias and (name == alias or name.startswith(alias + " ") or (" " + alias + " ") in (" " + name + " ")) for alias in aliases):
            contains.append(player)
    return contains[0] if len(contains) == 1 else None


def current_hit_ab(PlateAppearance, Ledger, team_id, player_id, scope):
    games = PlateAppearance.objects.filter(
        game__team_id=team_id,
        game__game_type=scope,
    ).exclude(game__status="CANCELLED").filter(player_id=player_id)

    hits = games.filter(result__in=("1B", "2B", "3B", "HR")).count()
    ab = games.exclude(result__in=("BB", "SF")).count()

    ledger = Ledger.objects.filter(team_id=team_id, player_id=player_id, scope=scope)
    for row in ledger:
        hits += int(row.hits or 0)
        ab += int(row.ab or 0)
    return hits, ab


def apply_verified_totals(apps, schema_editor):
    SportsTeam = apps.get_model("platform_sports", "SportsTeam")
    SportsPlayer = apps.get_model("platform_sports", "SportsPlayer")
    SportsGame = apps.get_model("platform_sports", "SportsGame")
    PlateAppearance = apps.get_model("platform_sports", "SoftballPlateAppearance")
    Ledger = apps.get_model("platform_sports", "SoftballStatLedgerEntry")

    team = (
        SportsTeam.objects.filter(group_id=1, group__name__icontains="bed")
        .filter(group__name__icontains="spring")
        .first()
    )
    if not team or not getattr(team, "created_by_id", None):
        print("Bed Springs H/AB correction skipped: target team/creator not found.")
        return

    candidate_games = list(
        SportsGame.objects.filter(team_id=team.id)
        .exclude(status="CANCELLED")
        .filter(game_type__in=("LEAGUE", "TOURNAMENT"))
        .order_by("start_at", "id")
    )

    landmarks = [g for g in candidate_games if "landmark" in norm(g.opponent_name)]
    hope = [g for g in candidate_games if "hope hull" in norm(g.opponent_name)]
    vaughn = [g for g in candidate_games if "vaughn" in norm(g.opponent_name) and "forest" in norm(g.opponent_name)]
    fraser = [g for g in candidate_games if "fraser" in norm(g.opponent_name)]
    freedom = [g for g in candidate_games if "freedom" in norm(g.opponent_name)]

    if len(landmarks) < 2 or not hope or not vaughn or not fraser or not freedom:
        print("Bed Springs H/AB correction skipped: expected six-game slate was not found.")
        return

    # "Landmark 1" is the earlier meeting, "Landmark 2" the later meeting.
    landmark_1, landmark_2 = landmarks[-2], landmarks[-1]
    game_map = {
        "landmark_1": landmark_1,
        "landmark_2": landmark_2,
        "hope_hull": hope[-1],
        "vaughn_forest": vaughn[-1],
        "fraser": fraser[-1],
        "freedom": freedom[-1],
    }

    # Do not silently overwrite a later season. Only run while the verified sheet
    # represents the complete played League/Tournament slate for this team.
    played_ids = set(
        SportsGame.objects.filter(team_id=team.id, status="FINAL", game_type__in=("LEAGUE", "TOURNAMENT"))
        .values_list("id", flat=True)
    )
    sheet_ids = {game.id for game in game_map.values()}
    if played_ids and not played_ids.issubset(sheet_ids):
        print("Bed Springs H/AB correction skipped: additional final games exist beyond the verified six-game sheet.")
        return

    players = list(SportsPlayer.objects.filter(team_id=team.id, merged_into__isnull=True, is_active=True))
    targets = {}
    for game_key, stats in GAME_ROWS.items():
        game = game_map[game_key]
        scope = str(game.game_type or "").upper()
        if scope not in ("LEAGUE", "TOURNAMENT"):
            continue
        for player_key, (hits, ab) in stats.items():
            bucket = targets.setdefault((player_key, scope), [0, 0])
            bucket[0] += int(hits)
            bucket[1] += int(ab)

    updated = 0
    for (player_key, scope), (target_hits, target_ab) in targets.items():
        player = find_player(players, player_key)
        if not player:
            print(f"Bed Springs H/AB correction: player '{player_key}' not uniquely matched; skipped.")
            continue

        current_hits, current_ab = current_hit_ab(PlateAppearance, Ledger, team.id, player.id, scope)
        delta_hits = int(target_hits) - int(current_hits)
        delta_ab = int(target_ab) - int(current_ab)
        if not delta_hits and not delta_ab:
            continue

        Ledger.objects.create(
            team_id=team.id,
            player_id=player.id,
            season_name=(team.season_name or "2026")[:120],
            scope=scope,
            games=0,
            pa=0,
            ab=delta_ab,
            hits=delta_hits,
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
        updated += 1

    print(f"Bed Springs H/AB correction applied to {updated} player/scope rows.")


def reverse_verified_totals(apps, schema_editor):
    Ledger = apps.get_model("platform_sports", "SoftballStatLedgerEntry")
    Ledger.objects.filter(note=NOTE, source="CORRECTION").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("platform_sports", "0023_signed_stat_grid_adjustments"),
    ]

    operations = [
        migrations.RunPython(apply_verified_totals, reverse_verified_totals),
    ]
