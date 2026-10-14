from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

from .models import SoftballPlateAppearance, SportsGame
from .way_score import _approach_value, _execution_value, _impact_value, _quality_at_bat
from .way_models import SportsPlayerMetricRating, SportsTeamWeekMetric


def _safe_ratio(numerator, denominator):
    return float(numerator) / float(denominator) if denominator else 0.0


def _game_date(game):
    try:
        return timezone.localtime(game.start_at, ZoneInfo(game.timezone or "America/Chicago")).date()
    except (KeyError, ValueError):
        return timezone.localtime(game.start_at).date()


def _week_start(day):
    return day - timedelta(days=day.weekday())


def _team_execution_score(appearances):
    rows = defaultdict(lambda: {"pa": 0, "qab": 0, "approach": 0.0, "exec": 0.0, "exec_opp": 0, "impact": 0.0})
    for pa in appearances:
        row = rows[pa.player_id]
        row["pa"] += 1
        row["qab"] += 1 if _quality_at_bat(pa) else 0
        row["approach"] += _approach_value(pa)
        value, opportunity = _execution_value(pa)
        if opportunity:
            row["exec"] += value
            row["exec_opp"] += 1
        row["impact"] += _impact_value(pa)

    scores = []
    for row in rows.values():
        if not row["pa"]:
            continue
        qab = _safe_ratio(row["qab"], row["pa"])
        approach = _safe_ratio(row["approach"], row["pa"])
        execution = _safe_ratio(row["exec"], row["exec_opp"]) if row["exec_opp"] else approach
        impact = _safe_ratio(row["impact"], row["pa"])
        score = 100 * (.45 * execution + .30 * qab + .15 * approach + .10 * impact)
        scores.append((score, row["pa"]))
    total_pa = sum(pa for _, pa in scores)
    return round(sum(score * pa for score, pa in scores) / total_pa, 1) if total_pa else None


def _weekly_rating_map(team):
    grouped = defaultdict(lambda: defaultdict(list))
    ratings = SportsPlayerMetricRating.objects.filter(team=team, week_of__isnull=False).exclude(period_key="CURRENT")
    for row in ratings:
        grouped[row.week_of][row.metric_key].append(int(row.value))
    return {
        week: {key: round(sum(values) / len(values), 1) for key, values in metrics.items() if values}
        for week, metrics in grouped.items()
    }


def team_weekly_trend(team):
    games = list(team.games.filter(status=SportsGame.Status.FINAL).order_by("start_at", "id"))
    appearances = list(
        SoftballPlateAppearance.objects.filter(game__team=team, game__status=SportsGame.Status.FINAL)
        .select_related("game", "player").order_by("game__start_at", "sequence", "id")
    )

    games_by_week = defaultdict(list)
    pas_by_week = defaultdict(list)
    for game in games:
        games_by_week[_week_start(_game_date(game))].append(game)
    for pa in appearances:
        pas_by_week[_week_start(_game_date(pa.game))].append(pa)

    targets = {row.week_of: row for row in SportsTeamWeekMetric.objects.filter(team=team)}
    weekly_ratings = _weekly_rating_map(team)
    weeks = sorted(set(games_by_week) | set(targets) | set(weekly_ratings))
    rows = []
    running_runs = 0
    running_games = 0
    for week in weeks:
        week_games = games_by_week.get(week, [])
        game_count = len(week_games)
        runs = sum(int(game.runs_for or 0) for game in week_games)
        running_runs += runs
        running_games += game_count
        actual = round(runs / game_count, 2) if game_count else None
        target = targets.get(week)
        ratings = weekly_ratings.get(week, {})
        rows.append({
            "week_of": week.isoformat(),
            "label": week.strftime("%b %d").replace(" 0", " "),
            "games": game_count,
            "runs": runs,
            "actual_runs_per_game": actual,
            "season_runs_per_game": round(running_runs / running_games, 2) if running_games else None,
            "expected_runs_per_game": float(target.expected_runs_per_game) if target and target.expected_runs_per_game is not None else None,
            "team_execution_score": _team_execution_score(pas_by_week.get(week, [])),
            "team_coach_grade": ratings.get(SportsPlayerMetricRating.Metric.PLAYER_GRADE),
            "team_approach_grade": ratings.get(SportsPlayerMetricRating.Metric.PLATE_APPROACH),
            "team_execution_grade": ratings.get(SportsPlayerMetricRating.Metric.EXECUTION),
            "note": target.note if target else "",
        })

    current_ratings = list(SportsPlayerMetricRating.objects.filter(team=team, period_key="CURRENT").values("metric_key", "value"))
    rating_groups = defaultdict(list)
    for rating in current_ratings:
        rating_groups[rating["metric_key"]].append(int(rating["value"]))
    team_ratings = {key: round(sum(values) / len(values), 1) for key, values in rating_groups.items() if values}

    return {
        "team": {"id": team.id, "group": team.group_id, "name": team.group.name},
        "weeks": rows,
        "team_ratings": team_ratings,
        "score_scale": {"execution_score": [0, 100], "coach_ratings": [1, 10]},
        "principle": "Is the team better because of what we did?",
    }
