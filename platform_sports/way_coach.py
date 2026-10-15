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
        "label": "Start rallies / bases empty",
        "event_label": "rallies or traffic-starting opportunities",
        "action": "Become the inning starter: hunt one pitch you can drive, stay through the middle/opposite field, and prioritize reaching safely over forcing power.",
    },
    "TWO_OUT": {
        "label": "Two-out inning extension",
        "event_label": "two-out innings extended",
        "action": "Two outs changes the approach, not the goal. Extend the inning: attack a pitch you can handle, protect the opportunity, make quality contact, and trust the hitter behind you.",
    },
    "RUNNERS_ON": {
        "label": "Runners-on conversion",
        "event_label": "runners-on opportunities converted",
        "action": "Use the same swing you trust with nobody on. Decide the job before the pitch: score him when available, otherwise move him and pass the torch. Do not expand the zone trying to do too much.",
    },
    "EXECUTION": {
        "label": "Execution / decisions",
        "event_label": "team-value executions",
        "action": "Name the situation before every pitch: what does the team need, what is your part, then execute and reset. Grade the decision even when a well-hit ball becomes an out.",
    },
    "CONTACT": {
        "label": "Consistent contact",
        "event_label": "successful contact opportunities",
        "action": "Simplify pitch selection and own the strike you handle best. Eliminate low-value early swings and make the first two strikes count when you choose to attack.",
    },
}

FOCUS_PRIORITY = {
    "RUNNERS_ON": 1.35,
    "BASES_EMPTY": 1.15,
    "EXECUTION": 1.10,
    "CONTACT": 1.00,
    "TWO_OUT": 0.75,
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


def _lineup_band(slot):
    try:
        slot = int(slot)
    except (TypeError, ValueError):
        return {"key": "LOWER", "label": "Lower part of order", "slots": "8-10"}
    if slot <= 3:
        return {"key": "TOP", "label": "Top of order", "slots": "1-3"}
    if slot <= 7:
        return {"key": "MIDDLE", "label": "Middle of order", "slots": "4-7"}
    return {"key": "LOWER", "label": "Lower part of order", "slots": "8-10"}


def _focus_candidate(key, current, baseline, opportunities_per_game):
    if current is None or opportunities_per_game <= 0:
        return None
    target = _target(float(current), float(baseline) if baseline is not None else None)
    gap = max(0.0, target - float(current))
    added_events = gap * float(opportunities_per_game)
    low_value, high_value = RUN_VALUE[key]
    low = added_events * low_value
    high = added_events * high_value
    priority = ((low + high) / 2.0) * FOCUS_PRIORITY[key]
    return {
        "key": key,
        "label": FOCUS_META[key]["label"],
        "event_label": FOCUS_META[key]["event_label"],
        "action": FOCUS_META[key]["action"],
        "current": _round(current),
        "target": _round(target),
        "gap": _round(gap),
        "opportunities_per_game": _round(opportunities_per_game, 2),
        "projected_events_per_game": _round(added_events, 2),
        "projected_events_per_10_games": _round(added_events * 10.0, 1),
        "projected_runs_per_game_low": _round(low, 2),
        "projected_runs_per_game_high": _round(high, 2),
        "projected_runs_per_10_games_low": _round(low * 10.0, 1),
        "projected_runs_per_10_games_high": _round(high * 10.0, 1),
        "priority": priority,
    }


def _downside_candidate(key, current, opportunities_per_game, drop=0.05):
    if current is None or opportunities_per_game <= 0:
        return None
    current = float(current)
    decline = min(float(drop), current)
    floor = max(0.0, current - decline)
    lost_events = decline * float(opportunities_per_game)
    low_value, high_value = RUN_VALUE[key]
    return {
        "key": key,
        "label": FOCUS_META[key]["label"],
        "event_label": FOCUS_META[key]["event_label"],
        "current": _round(current),
        "floor": _round(floor),
        "drop": _round(decline),
        "opportunities_per_game": _round(opportunities_per_game, 2),
        "lost_events_per_game": _round(lost_events, 2),
        "lost_events_per_10_games": _round(lost_events * 10.0, 1),
        "projected_runs_lost_per_game_low": _round(lost_events * low_value, 2),
        "projected_runs_lost_per_game_high": _round(lost_events * high_value, 2),
        "projected_runs_lost_per_10_games_low": _round(lost_events * low_value * 10.0, 1),
        "projected_runs_lost_per_10_games_high": _round(lost_events * high_value * 10.0, 1),
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
            "slots": "8-10",
            "band_hint": "LOWER",
            "reason": "The early results are useful, but the sample is still too small to lock this player into a permanent offensive role.",
        }

    if avg is not None and team_avg is not None and rob is not None and team_rob is not None and avg >= team_avg and rob >= team_rob + 0.03:
        return {
            "role": "Run producer",
            "slots": "4-7",
            "band_hint": "MIDDLE",
            "reason": "Above-team contact plus strong runners-on production makes this player most valuable after the top of the order creates traffic.",
        }

    if avg is not None and team_avg is not None and empty is not None and team_empty is not None and avg >= team_avg and empty >= team_empty:
        return {
            "role": "Rally starter / table setter",
            "slots": "1-3",
            "band_hint": "TOP",
            "reason": "Above-team contact and strong bases-empty work fit a player who can start rallies and create traffic for the run producers behind him.",
        }

    if rob is not None and team_rob is not None and rob >= team_rob and two is not None and team_two is not None and two >= team_two:
        return {
            "role": "Connector / lineup turner",
            "slots": "6-9",
            "band_hint": "MIDDLE",
            "reason": "Runners-on and inning-extension results give this player value as a connector who can keep rallies alive and turn the lineup over.",
        }

    if avg is not None and team_avg is not None and avg >= team_avg and exe is not None and team_exe is not None and exe < team_exe:
        return {
            "role": "Run-producing bat, execution emphasis",
            "slots": "4-7",
            "band_hint": "MIDDLE",
            "reason": "The bat is producing enough for the middle, while better decisions and execution can turn that production into more team value.",
        }

    if avg is not None and team_avg is not None and avg >= team_avg - 0.025:
        return {
            "role": "Balanced connector",
            "slots": "5-8",
            "band_hint": "MIDDLE",
            "reason": "This profile is near the team offensive baseline and can connect the rally starters to the lower part of the order.",
        }

    return {
        "role": "Turnover / development bat",
        "slots": "8-10",
        "band_hint": "LOWER",
        "reason": "The best current value is protecting outs, improving the weakest situation, and helping the lineup turn back over to the highest-probability bats.",
    }


def _strength_for(row, team):
    dimensions = []
    for key, label in (("BASES_EMPTY", "Bases empty"), ("TWO_OUT", "Two outs"), ("RUNNERS_ON", "Runners on")):
        metric_key = {"BASES_EMPTY": "bases_empty", "TWO_OUT": "two_out", "RUNNERS_ON": "runners_on"}[key]
        metric = row.get(metric_key) or {}
        baseline = (team.get(metric_key) or {}).get("rate")
        current = metric.get("adjusted_rate")
        # Do not turn a 1-for-1 or 2-for-2 into a player identity. Three tracked
        # opportunities is the minimum before a situational split can be named a strength.
        if int(metric.get("ab") or 0) >= 3 and current is not None and baseline is not None:
            dimensions.append((float(current) - float(baseline), key, label, metric.get("rate"), current, baseline))
    avg = (row.get("season_batting") or {}).get("avg")
    team_avg = (team.get("season_batting") or {}).get("avg")
    if avg is not None and team_avg is not None:
        dimensions.append((float(avg) - float(team_avg), "CONTACT", "Season contact", avg, avg, team_avg))
    exe = row.get("execution_average")
    team_exe = team.get("execution_average")
    if exe is not None and team_exe is not None:
        dimensions.append((float(exe) - float(team_exe), "EXECUTION", "Execution", exe, exe, team_exe))
    if not dimensions:
        return {"key": None, "label": "Need more data", "value": None, "adjusted_value": None, "baseline": None, "delta": None}
    dimensions.sort(key=lambda item: item[0], reverse=True)
    delta, key, label, value, adjusted, baseline = dimensions[0]
    if delta <= 0:
        return {
            "key": None,
            "label": "No above-team strength established yet",
            "value": None,
            "adjusted_value": None,
            "baseline": None,
            "delta": _round(delta),
        }
    return {
        "key": key,
        "label": label,
        "value": _round(value) if value is not None else None,
        "adjusted_value": _round(adjusted) if adjusted is not None else None,
        "baseline": _round(baseline) if baseline is not None else None,
        "delta": _round(delta),
    }


def _scores(row, team):
    batting = row.get("season_batting") or {}
    avg = batting.get("avg")
    ab = int(batting.get("ab") or 0)
    confidence = min(1.0, float(ab) / 24.0) if ab else 0.0

    def stable(metric_key, team_key):
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

    # Rally creation and runners-on conversion intentionally outweigh two-out results.
    table = 0.35 * stable_avg + 0.45 * empty + 0.20 * stable_exe
    producer = 0.25 * stable_avg + 0.55 * rob + 0.05 * two + 0.15 * stable_exe
    bridge = 0.30 * stable_avg + 0.35 * empty + 0.15 * two + 0.20 * stable_exe
    overall = 0.30 * table + 0.50 * producer + 0.20 * bridge
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

    # Clear lineup bands: 1-3 rally starters, 4-7 traffic converters, 8+ turnover/bridge bats.
    order.extend(take_best("table_setter", min(3, len(remaining))))
    order.extend(take_best("run_producer", min(4, len(remaining))))
    order.extend(take_best("bridge", len(remaining)))

    output = []
    for index, row in enumerate(order, start=1):
        band = _lineup_band(index)
        output.append({
            "slot": index,
            "lineup_band": band,
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
        "lineup_band": metrics.get("lineup_band"),
        "focus_key": snapshot.focus_override or snapshot.focus_key,
        "focus_label": metrics.get("focus_label") or FOCUS_META.get(snapshot.focus_override or snapshot.focus_key, {}).get("label"),
        "projected_runs_per_game_low": float(snapshot.projected_runs_per_game_low),
        "projected_runs_per_game_high": float(snapshot.projected_runs_per_game_high),
        "coach_note": snapshot.coach_note,
        "metrics": metrics,
        "updated_at": snapshot.updated_at,
    }


def _opportunities_for_key(key, row, sample_games, batting_games, graded_pa):
    if key == "BASES_EMPTY":
        return float((row.get("bases_empty") or {}).get("ab") or 0) / float(max(1, sample_games))
    if key == "TWO_OUT":
        return float((row.get("two_out") or {}).get("ab") or 0) / float(max(1, sample_games))
    if key == "RUNNERS_ON":
        return float((row.get("runners_on") or {}).get("ab") or 0) / float(max(1, sample_games))
    if key == "EXECUTION":
        return float(graded_pa or 0) / float(max(1, batting_games))
    return float((row.get("season_batting") or {}).get("ab") or 0) / float(max(1, batting_games))


def _player_message(row, band, focus, downside):
    name = row["player"].get("display_name") or "Player"
    strength = row.get("strength") or {}
    focus_label = focus.get("label") or "next development area"
    runs_low = focus.get("projected_runs_per_game_low", 0)
    runs_high = focus.get("projected_runs_per_game_high", 0)
    events = focus.get("projected_events_per_10_games", 0)
    event_label = focus.get("event_label") or "successful opportunities"
    downside_text = ""
    if downside:
        downside_text = (
            f" Protecting {strength.get('label', 'your strongest area')} matters too: a .050 drop models to roughly "
            f"{downside.get('projected_runs_lost_per_game_low', 0):.2f}-{downside.get('projected_runs_lost_per_game_high', 0):.2f} fewer team runs per game."
        )
    return (
        f"{name}: {band['label']} profile. Your strongest current value is {strength.get('label', 'still being established')}. "
        f"Your next lever is {focus_label}. {focus.get('action', '')} If that moves to the shown target, the model estimates "
        f"about +{runs_low:.2f}-{runs_high:.2f} team runs per game and roughly {events:.1f} additional {event_label} over 10 games."
        f"{downside_text} SIT+ measures situational hitting results; EXE measures whether your total decision/action made the team better; QAB is the coach eye-test approach grade we are collecting going forward."
    )


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
        graded_pa = int(exec_row.get("graded_pa") or 0)
        row = {**row, "graded_execution_pa": graded_pa}
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
            candidate = _focus_candidate(
                key,
                metric.get("adjusted_rate"),
                baseline,
                _opportunities_for_key(key, row, sample_games, batting_games, graded_pa),
            )
            if candidate:
                candidates.append(candidate)

        exec_candidate = _focus_candidate(
            "EXECUTION",
            row.get("execution_average"),
            team_metrics.get("execution_average"),
            _opportunities_for_key("EXECUTION", row, sample_games, batting_games, graded_pa),
        )
        if exec_candidate:
            candidates.append(exec_candidate)

        batting = row.get("season_batting") or {}
        contact_candidate = _focus_candidate(
            "CONTACT",
            batting.get("avg"),
            (team_metrics.get("season_batting") or {}).get("avg"),
            _opportunities_for_key("CONTACT", row, sample_games, batting_games, graded_pa),
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
                "event_label": FOCUS_META.get(focus_key, FOCUS_META["CONTACT"])["event_label"],
                "action": FOCUS_META.get(focus_key, FOCUS_META["CONTACT"])["action"],
                "current": None,
                "target": None,
                "projected_events_per_game": 0.0,
                "projected_events_per_10_games": 0.0,
                "projected_runs_per_game_low": 0.0,
                "projected_runs_per_game_high": 0.0,
                "projected_runs_per_10_games_low": 0.0,
                "projected_runs_per_10_games_high": 0.0,
            }

        strength = _strength_for(row, team_metrics)
        strength_opps = _opportunities_for_key(strength.get("key"), row, sample_games, batting_games, graded_pa) if strength.get("key") else 0.0
        downside = _downside_candidate(strength.get("key"), strength.get("adjusted_value"), strength_opps) if strength.get("key") else None

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
            "strength": strength,
            "focus_label": focus.get("label"),
            "lineup_scores": scores,
            "downside": downside,
        }
        output = {
            "player": row["player"],
            "season_batting": batting,
            "situational_index": row.get("situational_index"),
            "execution_average": row.get("execution_average"),
            "sample_games": sample_games,
            "strength": strength,
            "recommended_role": role["role"],
            "recommended_slots": role["slots"],
            "role_reason": role["reason"],
            "role_band_hint": role["band_hint"],
            "effective_role": effective_role,
            "effective_slots": effective_slots,
            "lineup_scores": scores,
            "focus": {k: v for k, v in focus.items() if k != "priority"},
            "downside": downside,
            "focus_options": [{k: v for k, v in item.items() if k not in ("priority", "action")} for item in candidates],
            "coach_note": snapshot.coach_note if snapshot and can_manage else "",
            "has_override": bool(snapshot and (snapshot.role_override or snapshot.slots_override or snapshot.focus_override or snapshot.coach_note)),
            "history": history_by_player.get(player_id, [])[:8] if can_manage else [],
            "metrics": metrics,
        }
        rows.append(output)

    # Build the model order before member filtering so each player can see his own band/slot
    # without exposing the entire roster order.
    full_lineup = _build_lineup(rows)
    lineup_by_player = {int(item["player"]["id"]): item for item in full_lineup}
    for row in rows:
        item = lineup_by_player.get(int(row["player"]["id"]))
        band = item["lineup_band"] if item else _lineup_band(10)
        row["suggested_slot"] = item["slot"] if item else None
        row["lineup_band"] = band
        row["metrics"]["lineup_band"] = band
        row["player_message"] = _player_message(row, band, row["focus"], row.get("downside"))

    if not can_manage and user is not None:
        player_ids = set(team.players.filter(user=user, is_active=True, merged_into__isnull=True).values_list("id", flat=True))
        rows = [row for row in rows if int(row["player"]["id"]) in player_ids]

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
        "metric_distinction": {
            "sit_plus": "Situational hitting effectiveness. Weighted 50% runners on, 35% bases empty/rally creation, 15% two outs when all three samples exist.",
            "execution": "Did the player's total decision/action make the team better? Productive outs and correct team-first decisions can score well even without a hit.",
            "qab": "Coach eye-test of plate-appearance quality. Kept in the system and collected prospectively; not used to backfill unreliable historical analysis.",
        },
        "rows": rows,
        "suggested_order": full_lineup if can_manage else [],
        "projection_note": "Run gain/loss is a directional model, not a guarantee. It uses opportunity frequency, the gap to a target (or a .050 decline for downside), and context-specific run-value ranges. Rally/event counts are modeled successful opportunities, not guaranteed runs.",
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