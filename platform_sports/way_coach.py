from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from .way_models import SportsPlayerCoachSnapshot


RUN_VALUE = {
    "BASES_EMPTY": (0.30, 0.55),
    "TWO_OUT": (0.45, 0.75),
    "RUNNERS_ON": (0.55, 0.90),
    "EXECUTION": (0.30, 0.60),
    "CONTACT": (0.35, 0.65),
}

FOCUS_META = {
    "BASES_EMPTY": {
        "label": "Start innings / bases empty",
        "action": "Become the inning starter: hunt one pitch you can drive, stay through the middle/opposite field, and prioritize reaching safely over forcing power.",
    },
    "TWO_OUT": {
        "label": "Two-out hitting",
        "action": "Shorten the decision with two outs: protect the inning, attack a pitch you can handle, and make the next hitter possible. With two strikes, quality contact comes first.",
    },
    "RUNNERS_ON": {
        "label": "Runners-on execution",
        "action": "Use the same swing you trust with nobody on. Decide the job before the pitch: score him when available, otherwise move him and pass the torch. Do not expand the zone trying to do too much.",
    },
    "EXECUTION": {
        "label": "Execution / decisions",
        "action": "Name the situation before every pitch: what does the team need, what is your part, then execute and reset. Grade the decision even when a well-hit ball becomes an out.",
    },
    "CONTACT": {
        "label": "Consistent contact",
        "action": "Simplify pitch selection and own the strike you handle best. Eliminate low-value early swings and make the first two strikes count when you choose to attack.",
    },
}


def week_start(value: date | None = None) -> date:
    current = value or timezone.localdate()
    return current - timedelta(days=current.weekday())


def _safe(value, fallback=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)


def _round(value, digits=3):
    return round(float(value), digits)


def _target(current, baseline, stretch=0.05):
    if current is None:
        return baseline
    if baseline is None:
        return min(0.95, current + stretch)
    if current < baseline:
        return baseline
    return min(0.95, current + stretch)


def _focus_candidate(key, current, baseline, opportunities_per_game):
    if current is None or opportunities_per_game <= 0:
        return None
    target = _target(float(current), float(baseline) if baseline is not None else None)
    gap = max(0.0, target - float(current))
    added_events = gap * float(opportunities_per_game)
    low_value, high_value = RUN_VALUE[key]
    low = added_events * low_value
    high = added_events * high_value
    # Prioritize high-leverage contexts, but do not let a tiny sample dominate.
    leverage = {"RUNNERS_ON": 1.35, "TWO_OUT": 1.20, "EXECUTION": 1.15, "CONTACT": 1.0, "BASES_EMPTY": 0.90}[key]
    priority = ((low + high) / 2.0) * leverage
    return {
        "key": key,
        "label": FOCUS_META[key]["label"],
        "action": FOCUS_META[key]["action"],
        "current": _round(current),
        "target": _round(target),
        "gap": _round(gap),
        "opportunities_per_game": _round(opportunities_per_game, 2),
        "projected_runs_per_game_low": _round(low, 2),
        "projected_runs_per_game_high": _round(high, 2),
        "projected_runs_per_10_games_low": _round(low * 10.0, 1),
        "projected_runs_per_10_games_high": _round(high * 10.0, 1),
        "priority": priority,
    }


def _role_for(row, team):
    batting = row.get("season_batting") or {}
    avg = batting.get("avg")
    team_avg = (team.get("season_batting") or {}).get("avg")
    rob = (row.get("runners_on") or {}).get("adjusted_rate")
    team_rob = (team.get("runners_on") or {}).get("rate")
    empty = (row.get("bases_empty") or {}).get("adjusted_rate")
    team_empty = (team.get("bases_empty") or {}).get("rate")
    two = (row.get("two_out") or {}).get("adjusted_rate")
    team_two = (team.get("two_out") or {}).get("rate")
    exe = row.get("execution_average")
    team_exe = team.get("execution_average")
    ab = int(batting.get("ab") or 0)

    if ab < 8:
        return {
            "role": "Evaluation / flexible bat",
            "slots": "7-10",
            "reason": "The early results are useful, but the sample is still too small to lock this player into a permanent offensive role.",
        }

    if avg is not None and team_avg is not None and rob is not None and team_rob is not None and avg >= team_avg and rob >= team_rob + 0.03:
        return {
            "role": "Middle-order run producer",
            "slots": "3-5",
            "reason": "Above-team contact plus strong runners-on production makes this player most valuable when earlier hitters create traffic.",
        }

    if avg is not None and team_avg is not None and empty is not None and team_empty is not None and avg >= team_avg and empty >= team_empty:
        return {
            "role": "Top-order table setter",
            "slots": "1-3",
            "reason": "Above-team contact and strong bases-empty work fit a player who can start innings and create traffic for the middle of the order.",
        }

    if two is not None and team_two is not None and rob is not None and team_rob is not None and two >= team_two and rob >= team_rob:
        return {
            "role": "Bridge / second leadoff",
            "slots": "6-9",
            "reason": "The overall average may not lead the team, but two-out and runners-on performance can extend innings and turn the lineup back over.",
        }

    if avg is not None and team_avg is not None and avg >= team_avg and exe is not None and team_exe is not None and exe < team_exe:
        return {
            "role": "Middle-order bat, execution emphasis",
            "slots": "4-6",
            "reason": "The bat is producing enough for a run-producing slot, while better decisions and situational execution can make that production more efficient.",
        }

    if avg is not None and team_avg is not None and avg >= team_avg - 0.025:
        return {
            "role": "Balanced lineup connector",
            "slots": "5-8",
            "reason": "This profile is near the team offensive baseline and can connect the top and bottom halves depending on matchup, availability, and defense.",
        }

    return {
        "role": "Bottom-third turnover bat",
        "slots": "8-10",
        "reason": "The best current value is protecting outs, improving the weakest situation, and helping the lineup turn back over to the highest-probability bats.",
    }


def _strength_for(row, team):
    dimensions = []
    for key, label in (("bases_empty", "Bases empty"), ("two_out", "Two outs"), ("runners_on", "Runners on")):
        metric = row.get(key) or {}
        baseline = (team.get(key) or {}).get("rate")
        current = metric.get("adjusted_rate")
        if current is not None and baseline is not None:
            dimensions.append((float(current) - float(baseline), label, metric.get("rate")))
    avg = (row.get("season_batting") or {}).get("avg")
    team_avg = (team.get("season_batting") or {}).get("avg")
    if avg is not None and team_avg is not None:
        dimensions.append((float(avg) - float(team_avg), "Season contact", avg))
    exe = row.get("execution_average")
    team_exe = team.get("execution_average")
    if exe is not None and team_exe is not None:
        dimensions.append((float(exe) - float(team_exe), "Execution", exe))
    if not dimensions:
        return {"label": "Need more data", "value": None}
    dimensions.sort(key=lambda item: item[0], reverse=True)
    _, label, value = dimensions[0]
    return {"label": label, "value": _round(value) if value is not None else None}


def _scores(row, team):
    batting = row.get("season_batting") or {}
    avg = batting.get("avg")
    ab = int(batting.get("ab") or 0)
    confidence = min(1.0, float(ab) / 24.0) if ab else 0.0

    def stable(metric_key, team_key, fallback_key=None):
        metric = row.get(metric_key) or {}
        raw = metric.get("adjusted_rate")
        base = (team.get(team_key) or {}).get("rate")
        if raw is None:
            raw = base
        if raw is None:
            raw = 0.0
        if base is None:
            base = raw
        c = min(1.0, confidence + 0.15)
        return float(base) + (float(raw) - float(base)) * c

    team_avg = (team.get("season_batting") or {}).get("avg") or 0.0
    stable_avg = float(team_avg) + ((_safe(avg, team_avg) - float(team_avg)) * confidence)
    team_exe = _safe(team.get("execution_average"), 0.55)
    stable_exe = team_exe + ((_safe(row.get("execution_average"), team_exe) - team_exe) * confidence)
    empty = stable("bases_empty", "bases_empty")
    two = stable("two_out", "two_out")
    rob = stable("runners_on", "runners_on")

    table = 0.40 * stable_avg + 0.40 * empty + 0.20 * stable_exe
    producer = 0.25 * stable_avg + 0.45 * rob + 0.15 * two + 0.15 * stable_exe
    bridge = 0.30 * stable_avg + 0.25 * empty + 0.25 * two + 0.20 * stable_exe
    overall = 0.30 * table + 0.45 * producer + 0.25 * bridge
    return {
        "table_setter": _round(table),
        "run_producer": _round(producer),
        "bridge": _round(bridge),
        "overall": _round(overall),
        "confidence": _round(confidence),
    }


def _build_lineup(rows):
    eligible = [row for row in rows if int((row.get("season_batting") or {}).get("ab") or 0) > 0]
    if not eligible:
        return []

    remaining = eligible[:]
    order = []

    def take_best(score_key, count):
        nonlocal remaining
        selected = sorted(remaining, key=lambda row: (row["lineup_scores"][score_key], row["lineup_scores"]["confidence"]), reverse=True)[:count]
        chosen_ids = {int(row["player"]["id"]) for row in selected}
        remaining = [row for row in remaining if int(row["player"]["id"]) not in chosen_ids]
        return selected

    # Two inning starters, three traffic converters, then bridge/turnover hitters.
    order.extend(take_best("table_setter", min(2, len(remaining))))
    order.extend(take_best("run_producer", min(3, len(remaining))))
    order.extend(take_best("bridge", len(remaining)))

    output = []
    for index, row in enumerate(order, start=1):
        output.append({
            "slot": index,
            "player": row["player"],
            "role": row["effective_role"],
            "recommended_slots": row["effective_slots"],
            "score": row["lineup_scores"]["overall"],
            "confidence": row["lineup_scores"]["confidence"],
        })
    return output


def _history_row(snapshot):
    metrics = snapshot.metrics or {}
    return {
        "week_of": snapshot.week_of.isoformat(),
        "role": snapshot.role_override or snapshot.recommended_role,
        "slots": snapshot.slots_override or snapshot.recommended_slots,
        "focus_key": snapshot.focus_override or snapshot.focus_key,
        "focus_label": metrics.get("focus_label") or FOCUS_META.get(snapshot.focus_override or snapshot.focus_key, {}).get("label"),
        "projected_runs_per_game_low": float(snapshot.projected_runs_per_game_low),
        "projected_runs_per_game_high": float(snapshot.projected_runs_per_game_high),
        "coach_note": snapshot.coach_note,
        "metrics": metrics,
        "updated_at": snapshot.updated_at,
    }


def coach_box_payload(team, *, user=None, can_manage=False):
    # Imported lazily to avoid a module cycle: situational views already use the
    # execution helper from WayAnalyticsViewSet.
    from .way_score_views import _execution_totals_payload
    from .way_situational_views import situational_payload

    situational = situational_payload(team)
    team_metrics = situational.get("team") or {}
    execution = _execution_totals_payload(team)
    execution_by_player = {int(row["player"]["id"]): row for row in execution.get("rows", [])}
    current_week = week_start()

    current_snapshots = {
        row.player_id: row
        for row in SportsPlayerCoachSnapshot.objects.filter(team=team, week_of=current_week).select_related("player")
    }
    history_qs = SportsPlayerCoachSnapshot.objects.filter(team=team).select_related("player").order_by("-week_of", "player__display_name")
    history_by_player = {}
    for snapshot in history_qs:
        history_by_player.setdefault(snapshot.player_id, []).append(_history_row(snapshot))

    rows = []
    for row in situational.get("rows", []):
        player_id = int(row["player"]["id"])
        exec_row = execution_by_player.get(player_id, {})
        row = {**row, "graded_execution_pa": int(exec_row.get("graded_pa") or 0)}
        role = _role_for(row, team_metrics)
        scores = _scores(row, team_metrics)
        sample_games = int(row.get("sample_games") or 0)
        batting_games = int((row.get("season_batting") or {}).get("games") or situational.get("batting_sample_games") or 0)

        candidates = []
        for key, metric_key, team_key in (
            ("BASES_EMPTY", "bases_empty", "bases_empty"),
            ("TWO_OUT", "two_out", "two_out"),
            ("RUNNERS_ON", "runners_on", "runners_on"),
        ):
            metric = row.get(metric_key) or {}
            baseline = (team_metrics.get(team_key) or {}).get("rate")
            opp_per_game = (float(metric.get("ab") or 0) / float(sample_games)) if sample_games else 0.0
            candidate = _focus_candidate(key, metric.get("adjusted_rate"), baseline, opp_per_game)
            if candidate:
                candidates.append(candidate)

        graded_pa = int(exec_row.get("graded_pa") or 0)
        exec_games = max(1, batting_games)
        exec_candidate = _focus_candidate(
            "EXECUTION",
            row.get("execution_average"),
            team_metrics.get("execution_average"),
            float(graded_pa) / float(exec_games) if graded_pa else 0.0,
        )
        if exec_candidate:
            candidates.append(exec_candidate)

        batting = row.get("season_batting") or {}
        contact_candidate = _focus_candidate(
            "CONTACT",
            batting.get("avg"),
            (team_metrics.get("season_batting") or {}).get("avg"),
            float(batting.get("ab") or 0) / float(max(1, batting_games)),
        )
        if contact_candidate:
            candidates.append(contact_candidate)

        candidates.sort(key=lambda item: item["priority"], reverse=True)
        snapshot = current_snapshots.get(player_id)
        focus_key = snapshot.focus_override if snapshot and snapshot.focus_override else (candidates[0]["key"] if candidates else "CONTACT")
        focus = next((item for item in candidates if item["key"] == focus_key), candidates[0] if candidates else None)
        if focus is None:
            focus = {
                "key": focus_key,
                "label": FOCUS_META.get(focus_key, FOCUS_META["CONTACT"])["label"],
                "action": FOCUS_META.get(focus_key, FOCUS_META["CONTACT"])["action"],
                "current": None,
                "target": None,
                "projected_runs_per_game_low": 0.0,
                "projected_runs_per_game_high": 0.0,
                "projected_runs_per_10_games_low": 0.0,
                "projected_runs_per_10_games_high": 0.0,
            }

        effective_role = snapshot.role_override if snapshot and snapshot.role_override else role["role"]
        effective_slots = snapshot.slots_override if snapshot and snapshot.slots_override else role["slots"]
        metrics = {
            "avg": batting.get("avg"),
            "ab": batting.get("ab"),
            "hits": batting.get("h"),
            "situational_index": row.get("situational_index"),
            "execution_average": row.get("execution_average"),
            "bases_empty": row.get("bases_empty"),
            "two_out": row.get("two_out"),
            "runners_on": row.get("runners_on"),
            "strength": _strength_for(row, team_metrics),
            "focus_label": focus.get("label"),
            "lineup_scores": scores,
        }
        output = {
            "player": row["player"],
            "season_batting": batting,
            "situational_index": row.get("situational_index"),
            "execution_average": row.get("execution_average"),
            "sample_games": sample_games,
            "strength": metrics["strength"],
            "recommended_role": role["role"],
            "recommended_slots": role["slots"],
            "role_reason": role["reason"],
            "effective_role": effective_role,
            "effective_slots": effective_slots,
            "lineup_scores": scores,
            "focus": {k: v for k, v in focus.items() if k != "priority"},
            "focus_options": [{k: v for k, v in item.items() if k not in ("priority", "action")} for item in candidates],
            "coach_note": snapshot.coach_note if snapshot and can_manage else "",
            "has_override": bool(snapshot and (snapshot.role_override or snapshot.slots_override or snapshot.focus_override or snapshot.coach_note)),
            "history": history_by_player.get(player_id, [])[:8] if can_manage else [],
            "metrics": metrics,
        }
        rows.append(output)

    if not can_manage and user is not None:
        player_ids = set(team.players.filter(user=user, is_active=True, merged_into__isnull=True).values_list("id", flat=True))
        rows = [row for row in rows if int(row["player"]["id"]) in player_ids]

    lineup = _build_lineup(rows) if can_manage else []
    return {
        "week_of": current_week.isoformat(),
        "can_manage": can_manage,
        "team": {
            "season_batting": team_metrics.get("season_batting"),
            "bases_empty": team_metrics.get("bases_empty"),
            "two_out": team_metrics.get("two_out"),
            "runners_on": team_metrics.get("runners_on"),
            "execution_average": team_metrics.get("execution_average"),
        },
        "rows": rows,
        "suggested_order": lineup,
        "projection_note": "Run gain is a directional model, not a guarantee. It estimates extra team runs per game if the player moves the selected category toward the shown target, using his opportunities per game and context-specific run-value ranges. Small samples are intentionally treated conservatively.",
    }


def snapshot_coach_box(team, *, user, target_week=None):
    target_week = week_start(target_week)
    payload = coach_box_payload(team, user=user, can_manage=True)
    saved = []
    for row in payload.get("rows", []):
        player_id = int(row["player"]["id"])
        existing = SportsPlayerCoachSnapshot.objects.filter(team=team, player_id=player_id, week_of=target_week).first()
        defaults = {
            "recommended_role": row["recommended_role"],
            "recommended_slots": row["recommended_slots"],
            "role_reason": row["role_reason"],
            "focus_key": row["focus"]["key"],
            "coaching_action": row["focus"]["action"],
            "projected_runs_per_game_low": Decimal(str(row["focus"]["projected_runs_per_game_low"])),
            "projected_runs_per_game_high": Decimal(str(row["focus"]["projected_runs_per_game_high"])),
            "metrics": row["metrics"],
            "updated_by": user,
        }
        if existing:
            for field, value in defaults.items():
                setattr(existing, field, value)
            existing.save()
            snapshot = existing
        else:
            snapshot = SportsPlayerCoachSnapshot.objects.create(team=team, player_id=player_id, week_of=target_week, **defaults)
        saved.append(snapshot.id)
    return saved
