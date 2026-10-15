from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from platform_social.models import GroupMembership

from .models import SportsPlayer, SportsTeam
from .way_models import SportsPlayerSituationalSplit
from .way_score_views import _execution_totals_payload


MANAGER_ROLES = (
    GroupMembership.Role.OWNER,
    GroupMembership.Role.DIRECTOR,
    GroupMembership.Role.MANAGER,
)
PRIOR_OPPORTUNITIES = 5
SIT_PLUS_WEIGHTS = {
    "bases_empty": 0.35,
    "two_out": 0.15,
    "runners_on": 0.50,
}


def _rate(hits, at_bats):
    return round(float(hits) / float(at_bats), 3) if at_bats else None


def _adjusted_rate(hits, at_bats, team_rate):
    if not at_bats or team_rate is None:
        return None
    return round((float(hits) + PRIOR_OPPORTUNITIES * float(team_rate)) / (float(at_bats) + PRIOR_OPPORTUNITIES), 3)


def _band(value, team_rate):
    if value is None or team_rate is None:
        return "neutral"
    delta = float(value) - float(team_rate)
    if delta >= 0.05:
        return "green"
    if delta >= 0:
        return "yellow"
    return "red"


def _metric(hits, at_bats, team_rate):
    raw = _rate(hits, at_bats)
    adjusted = _adjusted_rate(hits, at_bats, team_rate)
    return {
        "h": int(hits or 0),
        "ab": int(at_bats or 0),
        "rate": raw,
        "delta": round(raw - team_rate, 3) if raw is not None and team_rate is not None else None,
        "raw_band": _band(raw, team_rate),
        "adjusted_rate": adjusted,
        "adjusted_delta": round(adjusted - team_rate, 3) if adjusted is not None and team_rate is not None else None,
        "band": _band(adjusted, team_rate),
    }


def _batting_metric(hits, at_bats, games, team_rate):
    rate = _rate(hits, at_bats)
    return {
        "games": int(games or 0),
        "h": int(hits or 0),
        "ab": int(at_bats or 0),
        "avg": rate,
        "delta": round(rate - team_rate, 3) if rate is not None and team_rate is not None else None,
        "band": _band(rate, team_rate),
    }


def _situational_index(metrics, team_totals):
    weighted_total = 0.0
    available_weight = 0.0
    for key, metric in metrics.items():
        baseline = team_totals[key]["rate"]
        adjusted = metric.get("adjusted_rate")
        if adjusted is None or not baseline:
            continue
        weight = SIT_PLUS_WEIGHTS[key]
        weighted_total += ((float(adjusted) / float(baseline)) * 100.0) * weight
        available_weight += weight
    if not available_weight:
        return None
    # Re-normalize the available contexts so missing data does not become a penalty.
    return round(weighted_total / available_weight, 1)


def situational_payload(team):
    season_name = team.season_name or ""
    split_rows = list(
        SportsPlayerSituationalSplit.objects.filter(team=team, season_name=season_name)
        .select_related("player")
    )
    by_player = {row.player_id: row for row in split_rows}

    team_totals = {
        "bases_empty": {
            "h": sum(row.bases_empty_hits for row in split_rows),
            "ab": sum(row.bases_empty_ab for row in split_rows),
        },
        "two_out": {
            "h": sum(row.two_out_hits for row in split_rows),
            "ab": sum(row.two_out_ab for row in split_rows),
        },
        "runners_on": {
            "h": sum(row.runners_on_hits for row in split_rows),
            "ab": sum(row.runners_on_ab for row in split_rows),
        },
    }
    for value in team_totals.values():
        value["rate"] = _rate(value["h"], value["ab"])

    batting_h = sum(row.batting_hits for row in split_rows)
    batting_ab = sum(row.batting_ab for row in split_rows)
    batting_games = max((row.batting_sample_games for row in split_rows), default=0)
    team_batting_rate = _rate(batting_h, batting_ab)

    execution = _execution_totals_payload(team)
    execution_by_player = {int(row["player"]["id"]): row for row in execution.get("rows", [])}

    players = list(
        team.players.filter(is_active=True, merged_into__isnull=True)
        .order_by("sort_order", "display_name", "id")
    )
    rows = []
    for player in players:
        split = by_player.get(player.id)
        exec_row = execution_by_player.get(player.id, {})
        if split:
            bases_empty = _metric(split.bases_empty_hits, split.bases_empty_ab, team_totals["bases_empty"]["rate"])
            two_out = _metric(split.two_out_hits, split.two_out_ab, team_totals["two_out"]["rate"])
            runners_on = _metric(split.runners_on_hits, split.runners_on_ab, team_totals["runners_on"]["rate"])
            batting = _batting_metric(split.batting_hits, split.batting_ab, split.batting_sample_games, team_batting_rate)
            situational_index = _situational_index(
                {
                    "bases_empty": bases_empty,
                    "two_out": two_out,
                    "runners_on": runners_on,
                },
                team_totals,
            )
        else:
            bases_empty = _metric(0, 0, team_totals["bases_empty"]["rate"])
            two_out = _metric(0, 0, team_totals["two_out"]["rate"])
            runners_on = _metric(0, 0, team_totals["runners_on"]["rate"])
            batting = _batting_metric(0, 0, 0, team_batting_rate)
            situational_index = None

        rows.append({
            "player": {
                "id": player.id,
                "display_name": player.display_name,
                "jersey_number": player.jersey_number,
                "primary_position": player.primary_position,
            },
            "season_name": season_name,
            "sample_games": int(split.sample_games) if split else 0,
            "season_batting": batting,
            "bases_empty": bases_empty,
            "two_out": two_out,
            "runners_on": runners_on,
            "situational_index": situational_index,
            "execution_average": exec_row.get("execution_average"),
            "execution_points": exec_row.get("execution_points"),
            "ba": batting.get("avg"),
            "detailed_ba": exec_row.get("ba"),
            "note": split.note if split else "",
            "updated_at": split.updated_at if split else None,
        })

    return {
        "season_name": season_name,
        "sample_games": max((row.sample_games for row in split_rows), default=0),
        "batting_sample_games": batting_games,
        "prior_opportunities": PRIOR_OPPORTUNITIES,
        "sit_plus_weights": {key: int(round(value * 100)) for key, value in SIT_PLUS_WEIGHTS.items()},
        "team": {
            **team_totals,
            "season_batting": {
                "games": batting_games,
                "h": batting_h,
                "ab": batting_ab,
                "avg": team_batting_rate,
            },
            "situational_index": 100.0,
            "execution_average": execution.get("team", {}).get("execution_average"),
            "ba": team_batting_rate,
            "detailed_ba": execution.get("team", {}).get("ba"),
        },
        "rows": rows,
        "definitions": {
            "season_batting": "Season H/AB snapshot. The current sample covers eight team games where available and is stored separately so incomplete extra-base-hit data from the newest games does not corrupt SLG or OPS.",
            "bases_empty": "Any tracked at-bat with nobody on base. This is not limited to inning leadoff hitters. It represents rally-starting/table-setting value.",
            "two_out": "Tracked at-bats that began with two outs. Two-out hitting matters, but SIT+ intentionally weights it below rally-starting and runners-on production.",
            "runners_on": "Tracked at-bats that began with at least one runner on base. This receives the largest SIT+ weight because converting traffic most directly supports run production.",
            "situational_index": "SIT+ compares each player's sample-size-stabilized situational rates with the team baseline. 100 is team average. Weighting is 50% runners on, 35% bases empty/rally starting, and 15% two outs. If a player lacks a sample in one context, the available weights are re-normalized rather than treating missing data as failure. Contexts remain separate so overlapping two-out/runners-on at-bats are not double-counted into one H/AB total.",
            "adjustment": f"Adjusted rates use a {PRIOR_OPPORTUNITIES}-opportunity team-average prior to reduce six-game small-sample outliers. Raw H/AB and raw rates remain visible.",
        },
    }


class WaySituationalViewSet(viewsets.ViewSet):
    """Team-visible, manager-editable batting snapshot and situational execution splits."""

    permission_classes = [IsAuthenticated]

    def _team_and_membership(self, request, pk):
        team = get_object_or_404(SportsTeam.objects.select_related("group"), pk=pk)
        membership = GroupMembership.objects.filter(
            group_id=team.group_id,
            user=request.user,
            status=GroupMembership.Status.ACTIVE,
        ).first()
        if not membership:
            return team, None, Response({"detail": "Active team membership required."}, status=status.HTTP_403_FORBIDDEN)
        if not bool((team.badge_rules or {}).get("way_we_play_enabled")):
            return team, membership, Response({"detail": "Way We Play analytics is not enabled for this team."}, status=status.HTTP_404_NOT_FOUND)
        return team, membership, None

    @staticmethod
    def _can_manage(membership):
        return bool(membership and membership.role in MANAGER_ROLES)

    def retrieve(self, request, pk=None):
        team, membership, error = self._team_and_membership(request, pk)
        if error:
            return error
        payload = situational_payload(team)
        payload["can_manage"] = self._can_manage(membership)
        return Response(payload)

    @action(detail=True, methods=["post"], url_path="save-player")
    def save_player(self, request, pk=None):
        team, membership, error = self._team_and_membership(request, pk)
        if error:
            return error
        if not self._can_manage(membership):
            return Response({"detail": "Manager access required."}, status=status.HTTP_403_FORBIDDEN)

        player = get_object_or_404(
            SportsPlayer,
            pk=request.data.get("player"),
            team=team,
            is_active=True,
            merged_into__isnull=True,
        )

        fields = (
            "sample_games",
            "bases_empty_hits", "bases_empty_ab",
            "two_out_hits", "two_out_ab",
            "runners_on_hits", "runners_on_ab",
            "batting_sample_games", "batting_hits", "batting_ab",
        )
        values = {}
        for field in fields:
            raw = request.data.get(field, 0)
            try:
                value = int(raw or 0)
            except (TypeError, ValueError):
                return Response({"detail": f"{field} must be a whole number."}, status=status.HTTP_400_BAD_REQUEST)
            if value < 0 or value > 9999:
                return Response({"detail": f"{field} is outside the supported range."}, status=status.HTTP_400_BAD_REQUEST)
            values[field] = value

        for hits_field, ab_field, label in (
            ("bases_empty_hits", "bases_empty_ab", "Bases empty"),
            ("two_out_hits", "two_out_ab", "Two outs"),
            ("runners_on_hits", "runners_on_ab", "Runners on"),
            ("batting_hits", "batting_ab", "Season batting"),
        ):
            if values[hits_field] > values[ab_field]:
                return Response({"detail": f"{label} hits cannot exceed at-bats."}, status=status.HTTP_400_BAD_REQUEST)

        season_name = str(request.data.get("season_name") or team.season_name or "").strip()[:80]
        note = str(request.data.get("note") or "Coach-adjusted situational/batting sample").strip()[:240]
        SportsPlayerSituationalSplit.objects.update_or_create(
            team=team,
            player=player,
            season_name=season_name,
            defaults={**values, "note": note, "updated_by": request.user},
        )
        payload = situational_payload(team)
        payload["can_manage"] = True
        saved = next((row for row in payload["rows"] if int(row["player"]["id"]) == player.id), None)
        return Response({"saved": saved, "team": payload["team"], "sample_games": payload["sample_games"], "batting_sample_games": payload["batting_sample_games"]})
