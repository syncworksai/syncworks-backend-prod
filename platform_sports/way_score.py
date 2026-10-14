"""Bed Springs' auditable Way We Play offensive analytics.

The score intentionally separates team-value execution from traditional slash-line
results. Every scored input comes from a completed official Game Book plate appearance.
Small samples are shrunk toward the team average so a 2-for-2 night does not outrank a
player who sustains the same quality over a meaningful number of trips.
"""
from __future__ import annotations

from collections import defaultdict

from .models import SoftballPlateAppearance, SportsGame


HITS = {
    SoftballPlateAppearance.Result.SINGLE,
    SoftballPlateAppearance.Result.DOUBLE,
    SoftballPlateAppearance.Result.TRIPLE,
    SoftballPlateAppearance.Result.HOME_RUN,
}
ON_BASE_RESULTS = HITS | {SoftballPlateAppearance.Result.WALK}

# Eight team-average plate appearances act as a prior. At 8 PA the player's observed
# rate receives 50% of the weight; at 24 PA it receives 75%. This keeps early-season
# leaderboards useful without pretending tiny samples are certain.
PRIOR_PA = 8.0


def _safe_ratio(numerator: float, denominator: float) -> float:
    return (float(numerator) / float(denominator)) if denominator else 0.0


def _cap(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _quality_at_bat(pa: SoftballPlateAppearance) -> bool:
    """Team-value QAB, not merely a hit.

    A hit/walk/sac fly is quality. So is a recorded situational success or a productive
    runner advance with no more than one out created. Strikeouts and multi-out damage are
    never rescued by incidental advancement.
    """
    if pa.result == SoftballPlateAppearance.Result.STRIKEOUT or int(pa.outs_recorded or 0) >= 2:
        return False
    if pa.result in ON_BASE_RESULTS or pa.result == SoftballPlateAppearance.Result.SAC_FLY:
        return True
    if pa.situation_success is True:
        return True
    if int(pa.runners_advanced or 0) > 0 and int(pa.outs_recorded or 0) <= 1:
        return True
    return False


def _approach_value(pa: SoftballPlateAppearance) -> float:
    """V1 observable plate-approach proxy on a 0..1 scale.

    We do not claim pitch-decision data that the current Game Book does not record.
    Instead this rewards controllable, observable execution: walk, successful objective,
    quality contact/result, productive advancement, and avoiding strikeout/multi-out harm.
    A later pitch/decision grade can replace or augment this term without changing the
    public Player Score contract.
    """
    outs = int(pa.outs_recorded or 0)
    if pa.result == SoftballPlateAppearance.Result.STRIKEOUT:
        return 0.0
    if outs >= 2:
        return 0.05

    candidates = [0.25]  # ordinary ball in play / neutral outcome
    if pa.result == SoftballPlateAppearance.Result.WALK:
        candidates.append(1.0)
    if pa.situation_success is True:
        candidates.append(0.95)
    if pa.result in HITS:
        candidates.append(0.90)
    if pa.result == SoftballPlateAppearance.Result.SAC_FLY:
        candidates.append(0.88)
    if int(pa.runners_advanced or 0) > 0:
        candidates.append(0.82)
    if pa.result == SoftballPlateAppearance.Result.REACHED_ON_ERROR:
        candidates.append(0.55)
    return max(candidates)


def _execution_value(pa: SoftballPlateAppearance) -> tuple[float, bool]:
    """Return situational execution value and whether the PA had a scorable objective."""
    has_context = bool(pa.situation_objective) or pa.situation_success is not None
    if has_context:
        if pa.situation_success is True:
            return 1.0, True
        if pa.situation_success is False:
            return 0.0, True

    # When explicit situation tagging was not used, only count objectively observable
    # productive execution. Do not manufacture failure from missing context.
    if int(pa.runners_advanced or 0) > 0 or int(pa.rbi or 0) > 0:
        if int(pa.outs_recorded or 0) >= 2:
            return 0.0, True
        return 1.0, True
    return 0.0, False


def _impact_value(pa: SoftballPlateAppearance) -> float:
    """Normalized offensive impact per PA, capped so one HR cannot own the composite."""
    bases = {
        SoftballPlateAppearance.Result.SINGLE: 1,
        SoftballPlateAppearance.Result.DOUBLE: 2,
        SoftballPlateAppearance.Result.TRIPLE: 3,
        SoftballPlateAppearance.Result.HOME_RUN: 4,
    }.get(pa.result, 0)
    on_base = 1 if pa.result == SoftballPlateAppearance.Result.WALK else 0
    positive = (
        bases
        + on_base
        + int(pa.rbi or 0)
        + 0.5 * int(pa.runs_scored or 0)
        + 0.5 * int(pa.runners_advanced or 0)
    )
    damage = 1.5 if int(pa.outs_recorded or 0) >= 2 else 0.0
    # 3 impact units is an intentionally high but reachable excellent PA.
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
    players = list(
        team.players.filter(is_active=True, merged_into__isnull=True)
        .order_by("sort_order", "display_name", "id")
    )
    rows = {player.id: _blank(player) for player in players}

    appearances = list(
        SoftballPlateAppearance.objects.filter(
            game__team=team,
            game__status=SportsGame.Status.FINAL,
        )
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
        if pa.result == SoftballPlateAppearance.Result.STRIKEOUT:
            row["strikeouts"] += 1
        if int(pa.outs_recorded or 0) >= 2:
            row["multi_outs"] += 1

    active_rows = [row for row in rows.values() if row["pa"] > 0]
    team_pa = sum(row["pa"] for row in active_rows)
    team_qab = sum(row["quality_at_bats"] for row in active_rows)
    team_approach = sum(row["approach_total"] for row in active_rows)
    team_exec_total = sum(row["execution_total"] for row in active_rows)
    team_exec_opp = sum(row["execution_opportunities"] for row in active_rows)
    team_impact = sum(row["impact_total"] for row in active_rows)

    team_rates = {
        "qab_rate": _safe_ratio(team_qab, team_pa),
        "approach_rate": _safe_ratio(team_approach, team_pa),
        "execution_rate": _safe_ratio(team_exec_total, team_exec_opp),
        "impact_rate": _safe_ratio(team_impact, team_pa),
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
        player_score = 100.0 * (
            0.35 * adjusted["qab_rate"]
            + 0.25 * adjusted["execution_rate"]
            + 0.25 * adjusted["approach_rate"]
            + 0.15 * adjusted["impact_rate"]
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
            "player_score": round(player_score, 1),
            "confidence": round(confidence * 100, 1),
            "strikeouts": row["strikeouts"],
            "multi_outs": row["multi_outs"],
        })

    output.sort(key=lambda item: (-item["player_score"], -item["pa"], item["player"]["display_name"].lower()))
    for index, item in enumerate(output, start=1):
        item["rank"] = index

    def leader(metric: str):
        eligible = [item for item in output if item["pa"] > 0]
        if not eligible:
            return None
        best = max(eligible, key=lambda item: (item[metric], item["pa"], -item["rank"]))
        return {"player": best["player"], "value": best[metric], "pa": best["pa"]}

    leaders = {
        "player_score": leader("player_score"),
        "quality_at_bats": leader("qab_pct"),
        "plate_approach": leader("plate_approach"),
        "situation_execution": leader("situation_execution"),
    }

    return {
        "team": {"id": team.id, "group": team.group_id, "name": team.group.name},
        "formula_version": "WAY-1.0",
        "minimum_display_pa": 1,
        "prior_pa": int(PRIOR_PA),
        "weights": {
            "quality_at_bats": 35,
            "situation_execution": 25,
            "plate_approach": 25,
            "offensive_impact": 15,
        },
        "team_rates": {key: round(value * 100, 1) for key, value in team_rates.items()},
        "leaders": leaders,
        "players": output,
        "methodology": {
            "quality_at_bat": "Hit, walk, sacrifice fly, recorded situational success, or productive runner advance without strikeout/multi-out damage.",
            "plate_approach": "V1 observable execution proxy from official Game Book outcomes and situational tags; it does not pretend pitch-decision data exists yet.",
            "sample_size": "Player rates are shrunk toward the team rate with an 8-PA prior; confidence reaches 100% at 24 PA for display purposes.",
            "source": "Final official Game Books only. Historical summary totals are excluded because they do not contain per-PA situational context.",
        },
    }
