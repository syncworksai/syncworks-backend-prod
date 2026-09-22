"""Earned softball card badges derived from completed official games + approved history.

Power / Contact can use actual scored plays and manager-entered historical stats.
Speed / Clutch require independently verified game moments: runs and RBI are
not enough to prove speed or a late tying/go-ahead hit.
"""
import re
from collections import defaultdict
from zoneinfo import ZoneInfo

from django.utils import timezone

from .models import SoftballPlateAppearance, SportsGame
from .ops_models import SoftballStatLedgerEntry, SportsPlayerMoment
from .badge_rules import get_team_badge_rules


LEVELS = (
    ("BRONZE", "#CD7F32"),
    ("SILVER", "#C0C0C0"),
    ("GOLD", "#EAB308"),
    ("DIAMOND", "#A78BFA"),
)
THRESHOLDS = {
    "POWER": (3, 8, 16, 30),
    "CONTACT": ((.450, 10), (.550, 20), (.650, 35), (.750, 60)),
    "SPEED": (3, 7, 12, 20),
    "CLUTCH": (1, 3, 5, 8),
}
HITS = ("1B", "2B", "3B", "HR")


def blank():
    return {
        "games": set(), "historical_games": 0, "pa": 0, "ab": 0,
        "h": 0, "double": 0, "triple": 0, "hr": 0, "bb": 0, "sf": 0,
        "rbi": 0, "runs": 0, "tb": 0,
    }


def sum_play(row, pa):
    row["games"].add(pa.game_id)
    row["pa"] += 1
    row["rbi"] += pa.rbi
    row["runs"] += pa.runs_scored
    if pa.result not in ("BB", "SF"):
        row["ab"] += 1
    if pa.result in HITS:
        row["h"] += 1
        row["tb"] += {"1B": 1, "2B": 2, "3B": 3, "HR": 4}[pa.result]
    if pa.result == "2B":
        row["double"] += 1
    elif pa.result == "3B":
        row["triple"] += 1
    elif pa.result == "HR":
        row["hr"] += 1
    elif pa.result == "BB":
        row["bb"] += 1
    elif pa.result == "SF":
        row["sf"] += 1


def sum_history(row, entry):
    row["historical_games"] += entry.games
    row["pa"] += entry.pa
    row["ab"] += entry.ab
    row["h"] += entry.hits
    row["double"] += entry.doubles
    row["triple"] += entry.triples
    row["hr"] += entry.home_runs
    row["bb"] += entry.walks
    row["sf"] += entry.sac_flies
    row["rbi"] += entry.rbi
    row["runs"] += entry.runs
    row["tb"] += max(0, entry.hits - entry.doubles - entry.triples - entry.home_runs) + (
        2 * entry.doubles + 3 * entry.triples + 4 * entry.home_runs
    )


def summary(row, *, label="", scope="", year=None, month=None, historical=False):
    ab = row["ab"]
    h = row["h"]
    bb = row["bb"]
    sf = row["sf"]
    avg = round(h / ab, 3) if ab else 0
    obp = round((h + bb) / (ab + bb + sf), 3) if (ab + bb + sf) else 0
    slg = round(row["tb"] / ab, 3) if ab else 0
    return {
        "label": label, "scope": scope, "year": year, "month": month,
        "historical": historical, "g": len(row["games"]) + row["historical_games"],
        **{k: row[k] for k in ("pa", "ab", "h", "double", "triple", "hr", "bb", "sf", "rbi", "runs", "tb")},
        "avg": avg, "obp": obp, "slg": slg, "ops": round(obp + slg, 3),
        "power_points": row["double"] + 2 * row["triple"] + 3 * row["hr"],
    }


def badge(category, *, points=0, avg=0, ab=0, verified_only=False, rules=None):
    settings = (rules or {}).get(category, {})
    thresholds = settings.get("thresholds", THRESHOLDS[category])
    enabled = settings.get("enabled", True)
    current = -1
    for i, minimum in enumerate(thresholds):
        achieved = enabled and ((avg >= minimum[0] and ab >= minimum[1]) if category == "CONTACT" else points >= minimum)
        if achieved:
            current = i
    tier = LEVELS[current][0] if current >= 0 else "LOCKED"
    next_index = current + 1
    if next_index >= len(thresholds):
        goal = None
        progress = 100
        remaining = "Maximum tier unlocked"
    else:
        threshold = thresholds[next_index]
        if category == "CONTACT":
            target_avg, target_ab = threshold
            progress = int(min(1, avg / target_avg if target_avg else 0, ab / target_ab) * 100)
            remaining = f"Bat {target_avg:.3f} with at least {target_ab} AB"
            goal = {"avg": target_avg, "ab": target_ab}
        else:
            progress = min(100, int(100 * points / threshold))
            remaining = f"{max(0, threshold - points)} more verified points to {LEVELS[next_index][0].title()}"
            goal = threshold
    return {
        "key": category, "tier": tier, "achieved": current >= 0,
        "enabled": enabled, "thresholds": thresholds,
        "border_color": LEVELS[current][1] if current >= 0 else "#334155",
        "levels_unlocked": [level for level, _ in LEVELS[:current+1]],
        "next_tier": LEVELS[next_index][0] if next_index < len(LEVELS) else None,
        "next_goal": goal, "progress": progress, "next_description": remaining,
        "points": points if category != "CONTACT" else None,
        "avg": avg if category == "CONTACT" else None,
        "ab": ab if category == "CONTACT" else None,
        "verified_only": verified_only,
    }


def local_game_date(game):
    try:
        tz = ZoneInfo(game.timezone or "America/Chicago")
        return timezone.localtime(game.start_at, tz).date()
    except (KeyError, ValueError):
        return game.start_at.date()


def card_progress(player):
    current_year = timezone.localdate().year
    season = player.team.season_name or str(current_year)
    year_match = re.search(r"\b(?:19|20)\d{2}\b", season)
    season_year = int(year_match.group()) if year_match else current_year
    all_time = blank()
    season_totals = blank()
    yearly = defaultdict(blank)
    monthly = defaultdict(blank)
    by_competition = defaultdict(blank)
    by_season = defaultdict(blank)
    # A card earns achievements only from completed games. A reopened/undone
    # Game Book automatically removes stats until it is final again.
    official = list(SoftballPlateAppearance.objects.filter(
        player=player, game__status=SportsGame.Status.FINAL,
    ).select_related("game").order_by("game__start_at", "sequence"))
    for pa in official:
        game = pa.game
        game_date = local_game_date(game)
        comp = game.game_type
        for row in (
            all_time, yearly[game_date.year],
            monthly[(game_date.year, game_date.month)],
            by_competition[comp],
            by_season[(game_date.year, comp)],
        ):
            sum_play(row, pa)
        if game_date.year == season_year:
            sum_play(season_totals, pa)

    # Legacy manager-entered history has a season, but generally no game date.
    # Never manufacture a monthly breakout for it.
    historical = list(player.stat_ledger_entries.filter(
        scope__in=(SoftballStatLedgerEntry.Scope.LEAGUE, SoftballStatLedgerEntry.Scope.TOURNAMENT),
    ).order_by("id"))
    for entry in historical:
        match = re.search(r"\b(?:19|20)\d{2}\b", entry.season_name or "")
        hist_year = int(match.group()) if match else None
        for row in (all_time, by_competition[entry.scope]):
            sum_history(row, entry)
        if hist_year:
            sum_history(yearly[hist_year], entry)
            sum_history(by_season[(hist_year, entry.scope)], entry)
        if hist_year == season_year and (not player.team.season_name or
                                           (entry.season_name or "").strip() == player.team.season_name.strip()):
            sum_history(season_totals, entry)

    moments = list(SportsPlayerMoment.objects.filter(
        player=player, game__status=SportsGame.Status.FINAL,
    ).select_related("game"))
    speed = clutch = 0
    for moment in moments:
        if local_game_date(moment.game).year != season_year:
            continue
        if moment.kind in (SportsPlayerMoment.Kind.EXTRA_BASE, SportsPlayerMoment.Kind.STEAL):
            speed += 1
        elif moment.kind in (SportsPlayerMoment.Kind.TYING_HIT, SportsPlayerMoment.Kind.GO_AHEAD_HIT):
            clutch += 1

    season_row = summary(season_totals, label=season, year=season_year)
    rules = get_team_badge_rules(player.team)
    badges = [
        badge("POWER", points=season_row["power_points"], rules=rules),
        badge("CONTACT", avg=season_row["avg"], ab=season_row["ab"], rules=rules),
        badge("SPEED", points=speed, verified_only=True, rules=rules),
        badge("CLUTCH", points=clutch, verified_only=True, rules=rules),
    ]
    achieved = [item for item in badges if item["achieved"]]
    current_max = max((len(b["levels_unlocked"]) for b in achieved), default=0)
    ring = LEVELS[current_max - 1][1] if current_max else "#334155"
    return {
        "player": player.pk, "season": season, "season_year": season_year,
        "season_totals": season_row,
        "career_totals": summary(all_time, label="Career"),
        "badges": badges, "achieved_count": len(achieved), "card_border": ring,
        "badge_rules": rules,
        "year_splits": [
            summary(row, label=str(year), year=year)
            for year, row in sorted(yearly.items(), reverse=True)
        ],
        "month_splits": [
            summary(row, label=f"{year}-{month:02d}", year=year, month=month)
            for (year, month), row in sorted(monthly.items(), reverse=True)
        ],
        "competition_splits": [
            summary(row, label=label.title(), scope=label)
            for label, row in sorted(by_competition.items())
        ],
        "season_splits": [
            summary(row, label=f"{year} · {scope.title()}", year=year, scope=scope)
            for (year, scope), row in sorted(by_season.items(), reverse=True)
        ],
        "verified_moments": [
            {
                "id": m.id, "kind": m.kind, "game": m.game_id,
                "opponent_name": m.game.opponent_name,
                "date": local_game_date(m.game).isoformat(),
            } for m in sorted(moments, key=lambda m: m.game.start_at, reverse=True)[:30]
        ],
        "badge_policy": "Power and Contact use completed official Game Books plus manager-entered dated season history. Speed and Clutch require verified, staff-recorded game moments.",
    }
