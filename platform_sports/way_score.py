"""Bed Springs' auditable Way We Play execution analytics.

The score is intentionally NOT a batting-average leaderboard. Its primary question is:
"Did this player's decisions and execution leave the team in a better position?"
Every scored input comes from a completed official Game Book plate appearance. Small
samples are stabilized toward the team rate so a tiny hot streak does not become the
team standard.
"""
from __future__ import annotations

from .models import SoftballPlateAppearance, SportsGame


HITS = {
    SoftballPlateAppearance.Result.SINGLE,
    SoftballPlateAppearance.Result.DOUBLE,
    SoftballPlateAppearance.Result.TRIPLE,
    SoftballPlateAppearance.Result.HOME_RUN,
}
ON_BASE_RESULTS = HITS | {SoftballPlateAppearance.Result.WALK}
PRIOR_PA = 8.0


def _safe_ratio(numerator: float, denominator: float) -> float:
    return (float(numerator) / float(denominator)) if denominator else 0.0


def _cap(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _quality_at_bat(pa: SoftballPlateAppearance) -> bool:
    """Did the PA create team value, independent of batting average?"""
    outs = int(pa.outs_recorded or 0)
    if pa.result == SoftballPlateAppearance.Result.STRIKEOUT or outs >= 2:
        return False
    if pa.situation_success is True:
        return True
    if int(pa.runners_advanced or 0) > 0 or int(pa.rbi or 0) > 0:
        return True
    if pa.result in ON_BASE_RESULTS or pa.result == SoftballPlateAppearance.Result.SAC_FLY:
        return True
    return False


def _approach_value(pa: SoftballPlateAppearance) -> float:
    """Observable process/approach proxy, not a slash-line reward."""
    outs = int(pa.outs_recorded or 0)
    if pa.result == SoftballPlateAppearance.Result.STRIKEOUT:
        return 0.0
    if outs >= 2:
        return 0.05
    candidates = [0.30]
    if pa.situation_success is True:
        candidates.append(1.0)
    if int(pa.runners_advanced or 0) > 0:
        candidates.append(0.90)
    if pa.result == SoftballPlateAppearance.Result.SAC_FLY:
        candidates.append(0.92)
    if pa.result == SoftballPlateAppearance.Result.WALK:
        candidates.append(0.88)
    if pa.result in HITS:
        candidates.append(0.82)
    if pa.result == SoftballPlateAppearance.Result.REACHED_ON_ERROR:
        candidates.append(0.58)
    return max(candidates)


def _execution_value(pa: SoftballPlateAppearance) -> tuple[float, bool]:
    """Score whether the hitter executed what the TEAM needed in a scorable spot."""
    has_context = bool(pa.situation_objective) or pa.situation_success is not None
    if has_context:
        if pa.situation_success is True:
            return 1.0, True
        if pa.situation_success is False:
            return 0.0, True

    # If no coach-tagged objective exists, use only obvious team-value evidence.
    # We never manufacture a failure from missing context.
    if int(pa.outs_recorded or 0) >= 2:
        return 0.0, True
    if int(pa.runners_advanced or 0) > 0 or int(pa.rbi or 0) > 0:
        return 1.0, True
    if pa.result == SoftballPlateAppearance.Result.SAC_FLY:
        return 1.0, True
    return 0.0, False


def _impact_value(pa: SoftballPlateAppearance) -> float:
    """Small supporting production term; raw power cannot dominate the score."""
    bases = {
        SoftballPlateAppearance.Result.SINGLE: 1,
        SoftballPlateAppearance.Result.DOUBLE: 2,
        SoftballPlateAppearance.Result.TRIPLE: 3,
        SoftballPlateAppearance.Result.HOME_RUN: 4,
    }.get(pa.result, 0)
    on_base = 1 if pa.result == SoftballPlateAppearance.Result.WALK else 0
    positive = bases + on_base + int(pa.rbi or 0) + 0.5 * int(pa.runs_scored or 0) + 0.5 * int(pa.runners_advanced or 0)
    damage = 1.75 if int(pa.outs_recorded or 0) >= 2 else 0.0
    return _cap((positive - damage) / 3.0)


def _blank(player) -> dict:
    return {
        "player": {
            "id": player.id,
            "display_name": player.display_name,
            "jersey_number": player.jersey_number,
            "primary_position": player.primary_position,
        },
        "pa": 0,
        "quality_at_bats": 0,
        "approach_total": 0.0,
        "execution_total": 0.0,
        "execution_opportunities": 0,
        "impact_total": 0.0,
        "strikeouts": 0,
        "multi_outs": 0,
        "productive_advances": 0,
    }


def _raw_metrics(row: dict) -> dict:
    pa = row["pa"]
    return {
        "qab_rate": _safe_ratio(row["quality_at_bats"], pa),
        "approach_rate": _safe_ratio(row["approach_total"], pa),
        "execution_rate": _safe_ratio(row["execution_total"], row["execution_opportunities"]),
        "impact_rate": _safe_ratio(row["impact_total"], pa),
    }


def _shrink(observed: float, team_rate: float, sample: int, prior: float = PRIOR_PA) -> float:
    return ((observed * sample) + (team_rate * prior)) / (sample + prior) if (sample + prior) else team_rate


def team_way_score(team) -> dict:
    players = list(team.players.filter(is_active=True, merged_into__isnull=True).order_by("sort_order", "display_name", "id"))
    rows = {player.id: _blank(player) for player in players}

    appearances = list(
        SoftballPlateAppearance.objects.filter(game__team=team, game__status=SportsGame.Status.FINAL)
        .select_related("player", "game")
        .order_by("game__start_at", "sequence", "id")
    )

    for pa in appearances:
        row = rows.get(pa.player_id)
        if row is None:
            row = _blank(pa.player)
            rows[pa.player_id] = row
        row["pa"] += 1
        if _quality_at_bat(pa):
            row["quality_at_bats"] += 1
        row["approach_total"] += _approach_value(pa)
        execution, has_opportunity = _execution_value(pa)
        if has_opportunity:
            row["execution_total"] += execution
            row["execution_opportunities"] += 1
        row["impact_total"] += _impact_value(pa)
        row["productive_advances"] += int(pa.runners_advanced or 0)
        if pa.result == SoftballPlateAppearance.Result.STRIKEOUT:
            row["strikeouts"] += 1
        if int(pa.outs_recorded or 0) >= 2:
            row["multi_outs"] += 1

    active_rows = [row for row in rows.values() if row["pa"] > 0]
    team_pa = sum(row["pa"] for row in active_rows)
    team_rates = {
        "qab_rate": _safe_ratio(sum(row["quality_at_bats"] for row in active_rows), team_pa),
        "approach_rate": _safe_ratio(sum(row["approach_total"] for row in active_rows), team_pa),
        "execution_rate": _safe_ratio(sum(row["execution_total"] for row in active_rows), sum(row["execution_opportunities"] for row in active_rows)),
        "impact_rate": _safe_ratio(sum(row["impact_total"] for row in active_rows), team_pa),
    }

    output = []
    for row in rows.values():
        raw = _raw_metrics(row)
        pa = row["pa"]
        exec_sample = row["execution_opportunities"]
        adjusted = {
            "qab_rate": _shrink(raw["qab_rate"], team_rates["qab_rate"], pa),
            "approach_rate": _shrink(raw["approach_rate"], team_rates["approach_rate"], pa),
            "execution_rate": _shrink(raw["execution_rate"], team_rates["execution_rate"], exec_sample),
            "impact_rate": _shrink(raw["impact_rate"], team_rates["impact_rate"], pa),
        }

        # WAY-1.1: execution and team improvement dominate; raw output is intentionally minor.
        player_score = 100.0 * (
            0.45 * adjusted["execution_rate"]
            + 0.30 * adjusted["qab_rate"]
            + 0.15 * adjusted["approach_rate"]
            + 0.10 * adjusted["impact_rate"]
        )
        confidence = _cap(pa / 24.0)
        output.append({
            "player": row["player"],
            "pa": pa,
            "quality_at_bats": row["quality_at_bats"],
            "qab_pct": round(raw["qab_rate"] * 100, 1),
            "plate_approach": round(adjusted["approach_rate"] * 100, 1),
            "situation_execution": round(adjusted["execution_rate"] * 100, 1),
            "execution_opportunities": exec_sample,
            "impact": round(adjusted["impact_rate"] * 100, 1),
            "execution_score": round(player_score, 1),
            "player_score": round(player_score, 1),
            "confidence": round(confidence * 100, 1),
            "strikeouts": row["strikeouts"],
            "multi_outs": row["multi_outs"],
            "productive_advances": row["productive_advances"],
        })

    output.sort(key=lambda item: (-item["execution_score"], -item["pa"], item["player"]["display_name"].lower()))
    for index, item in enumerate(output, start=1):
        item["rank"] = index

    def leader(metric: str):
        eligible = [item for item in output if item["pa"] > 0]
        if not eligible:
            return None
        best = max(eligible, key=lambda item: (item[metric], item["pa"], -item["rank"]))
        return {"player": best["player"], "value": best[metric], "pa": best["pa"]}

    leaders = {
        "player_score": leader("execution_score"),
        "execution_score": leader("execution_score"),
        "quality_at_bats": leader("qab_pct"),
        "plate_approach": leader("plate_approach"),
        "situation_execution": leader("situation_execution"),
    }

    return {
        "team": {"id": team.id, "group": team.group_id, "name": team.group.name},
        "formula_version": "WAY-1.1",
        "score_name": "Execution Score",
        "score_question": "Is the team better because of what I did?",
        "minimum_display_pa": 1,
        "prior_pa": int(PRIOR_PA),
        "weights": {
            "situation_execution": 45,
            "quality_at_bats": 30,
            "plate_approach": 15,
            "offensive_impact": 10,
        },
        "team_rates": {key: round(value * 100, 1) for key, value in team_rates.items()},
        "leaders": leaders,
        "players": output,
        "methodology": {
            "execution": "The largest term. Did the player accomplish the situational objective or create objectively productive team value?",
            "quality_at_bat": "Did the plate appearance improve the team's position, even when it did not become a hit?",
            "plate_approach": "Observable decision/process quality from the Game Book; raw batting average is not part of the formula.",
            "impact": "Runs, bases and production matter, but this term is intentionally small so power cannot overpower execution.",
            "sample_size": "Rates are stabilized toward the team rate with an 8-PA prior; confidence reaches 100% at 24 PA for display purposes.",
            "source": "Final official Game Books only. Historical summary totals remain useful for context but are excluded from Execution Score when they lack situational detail.",
        },
    }
