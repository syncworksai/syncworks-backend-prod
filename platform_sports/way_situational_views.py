from __future__ import annotations

from statistics import mean

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


def _rate(numerator, denominator):
    return round(float(numerator) / float(denominator), 3) if denominator else None


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


def _batting_metric(*, hits, at_bats, games, doubles=0, triples=0, home_runs=0, walks=0, sac_flies=0, team_rate=None):
    hits = int(hits or 0)
    at_bats = int(at_bats or 0)
    doubles = int(doubles or 0)
    triples = int(triples or 0)
    home_runs = int(home_runs or 0)
    walks = int(walks or 0)
    sac_flies = int(sac_flies or 0)
    singles = max(0, hits - doubles - triples - home_runs)
    total_bases = hits + doubles + (2 * triples) + (3 * home_runs)
    avg = _rate(hits, at_bats)
    obp = _rate(hits + walks, at_bats + walks + sac_flies)
    slg = _rate(total_bases, at_bats)
    ops = round(obp + slg, 3) if obp is not None and slg is not None else None
    return {
        "games": int(games or 0),
        "pa": at_bats + walks + sac_flies,
        "h": hits,
        "ab": at_bats,
        "single": singles,
        "double": doubles,
        "triple": triples,
        "hr": home_runs,
        "bb": walks,
        "sf": sac_flies,
        "tb": total_bases,
        "avg": avg,
        "obp": obp,
        "slg": slg,
        "ops": ops,
        "delta": round(avg - team_rate, 3) if avg is not None and team_rate is not None else None,
        "band": _band(avg, team_rate),
    }


def situational_payload(team):
    season_name = team.season_name or ""
    split_rows = list(
        SportsPlayerSituationalSplit.objects.filter(team=team, season_name=season_name)
        .select_related("player")
    )
    by_player = {row.player_id: row for row in split_rows}

    team_totals = {
        "bases_empty": {"h": sum(row.bases_empty_hits for row in split_rows), "ab": sum(row.bases_empty_ab for row in split_rows)},
        "two_out": {"h": sum(row.two_out_hits for row in split_rows), "ab": sum(row.two_out_ab for row in split_rows)},
        "runners_on": {"h": sum(row.runners_on_hits for row in split_rows), "ab": sum(row.runners_on_ab for row in split_rows)},
    }
    for value in team_totals.values():
        value["rate"] = _rate(value["h"], value["ab"])

    batting_h = sum(row.batting_hits for row in split_rows)
    batting_ab = sum(row.batting_ab for row in split_rows)
    batting_games = max((row.batting_sample_games for row in split_rows), default=0)
    batting_doubles = sum(row.batting_doubles for row in split_rows)
    batting_triples = sum(row.batting_triples for row in split_rows)
    batting_home_runs = sum(row.batting_home_runs for row in split_rows)
    batting_walks = sum(row.batting_walks for row in split_rows)
    batting_sac_flies = sum(row.batting_sac_flies for row in split_rows)
    team_batting_rate = _rate(batting_h, batting_ab)
    team_batting = _batting_metric(
        hits=batting_h,
        at_bats=batting_ab,
        games=batting_games,
        doubles=batting_doubles,
        triples=batting_triples,
        home_runs=batting_home_runs,
        walks=batting_walks,
        sac_flies=batting_sac_flies,
        team_rate=team_batting_rate,
    )

    execution = _execution_totals_payload(team)
    execution_by_player = {int(row["player"]["id"]): row for row in execution.get("rows", [])}

    players = list(team.players.filter(is_active=True, merged_into__isnull=True).order_by("sort_order", "display_name", "id"))
    rows = []
    for player in players:
        split = by_player.get(player.id)
        exec_row = execution_by_player.get(player.id, {})
        if split:
            bases_empty = _metric(split.bases_empty_hits, split.bases_empty_ab, team_totals["bases_empty"]["rate"])
            two_out = _metric(split.two_out_hits, split.two_out_ab, team_totals["two_out"]["rate"])
            runners_on = _metric(split.runners_on_hits, split.runners_on_ab, team_totals["runners_on"]["rate"])
            batting = _batting_metric(
                hits=split.batting_hits,
                at_bats=split.batting_ab,
                games=split.batting_sample_games,
                doubles=split.batting_doubles,
                triples=split.batting_triples,
                home_runs=split.batting_home_runs,
                walks=split.batting_walks,
                sac_flies=split.batting_sac_flies,
                team_rate=team_batting_rate,
            )
            index_parts = []
            for metric, key in ((bases_empty, "bases_empty"), (two_out, "two_out"), (runners_on, "runners_on")):
                baseline = team_totals[key]["rate"]
                if metric["adjusted_rate"] is not None and baseline:
                    index_parts.append((metric["adjusted_rate"] / baseline) * 100.0)
            situational_index = round(mean(index_parts), 1) if index_parts else None
        else:
            bases_empty = _metric(0, 0, team_totals["bases_empty"]["rate"])
            two_out = _metric(0, 0, team_totals["two_out"]["rate"])
            runners_on = _metric(0, 0, team_totals["runners_on"]["rate"])
            batting = _batting_metric(hits=0, at_bats=0, games=0, team_rate=team_batting_rate)
            situational_index = None

        rows.append({
            "player": {"id": player.id, "display_name": player.display_name, "jersey_number": player.jersey_number, "primary_position": player.primary_position},
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
        "team": {
            **team_totals,
            "season_batting": team_batting,
            "situational_index": 100.0,
            "execution_average": execution.get("team", {}).get("execution_average"),
            "ba": team_batting_rate,
            "detailed_ba": execution.get("team", {}).get("ba"),
        },
        "rows": rows,
        "definitions": {
            "season_batting": "Season batting snapshot. H/AB is coach-authoritative; 2B/3B/HR/BB/SF supply OBP, SLG and OPS. Singles are derived as H minus extra-base hits so an inconsistent singles column cannot corrupt total bases.",
            "bases_empty": "Any tracked at-bat with nobody on base. This is not limited to inning leadoff hitters.",
            "two_out": "Tracked at-bats that began with two outs.",
            "runners_on": "Tracked at-bats that began with at least one runner on base.",
            "situational_index": "SIT+ compares each player's sample-size-stabilized situational rates with the team baseline. 100 is team average. The three contexts are averaged as separate dimensions so overlapping two-out/runners-on at-bats are not double-counted into one H/AB total.",
            "adjustment": f"Adjusted situational rates use a {PRIOR_OPPORTUNITIES}-opportunity team-average prior to reduce six-game small-sample outliers. Raw H/AB remains visible.",
        },
    }


class WaySituationalViewSet(viewsets.ViewSet):
    """Team-visible, manager-editable batting snapshot and situational execution splits."""

    permission_classes = [IsAuthenticated]

    def _team_and_membership(self, request, pk):
        team = get_object_or_404(SportsTeam.objects.select_related("group"), pk=pk)
        membership = GroupMembership.objects.filter(group_id=team.group_id, user=request.user, status=GroupMembership.Status.ACTIVE).first()
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

        player = get_object_or_404(SportsPlayer, pk=request.data.get("player"), team=team, is_active=True, merged_into__isnull=True)
        season_name = str(request.data.get("season_name") or team.season_name or "").strip()[:80]
        existing = SportsPlayerSituationalSplit.objects.filter(team=team, player=player, season_name=season_name).first()
        fields = (
            "sample_games",
            "bases_empty_hits", "bases_empty_ab",
            "two_out_hits", "two_out_ab",
            "runners_on_hits", "runners_on_ab",
            "batting_sample_games", "batting_hits", "batting_ab",
            "batting_doubles", "batting_triples", "batting_home_runs", "batting_walks", "batting_sac_flies",
        )
        values = {}
        for field in fields:
            fallback = getattr(existing, field, 0) if existing is not None else 0
            raw = request.data.get(field, fallback)
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
        if values["batting_doubles"] + values["batting_triples"] + values["batting_home_runs"] > values["batting_hits"]:
            return Response({"detail": "Season extra-base hits cannot exceed season hits."}, status=status.HTTP_400_BAD_REQUEST)

        note = str(request.data.get("note") or (existing.note if existing else "Coach-adjusted situational/batting sample")).strip()[:240]
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
