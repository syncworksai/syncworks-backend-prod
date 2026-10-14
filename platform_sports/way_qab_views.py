from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from platform_social.models import GroupMembership

from .models import SportsPlayer, SportsTeam
from .views import softball_player_stats
from .way_models import SportsPlayerQABTotal


MANAGER_ROLES = (
    GroupMembership.Role.OWNER,
    GroupMembership.Role.DIRECTOR,
    GroupMembership.Role.MANAGER,
)
DEFAULT_GREEN_MIN = Decimal("2.00")
DEFAULT_YELLOW_MIN = Decimal("1.50")


def _membership(team, user):
    return GroupMembership.objects.filter(
        group_id=team.group_id,
        user=user,
        status=GroupMembership.Status.ACTIVE,
    ).first()


def _can_manage(membership):
    return bool(membership and membership.role in MANAGER_ROLES)


def _bands(team):
    rules = dict(team.badge_rules or {})
    raw = dict(rules.get("qab_score_bands") or {})
    try:
        green_min = Decimal(str(raw.get("green_min", DEFAULT_GREEN_MIN)))
    except (InvalidOperation, TypeError, ValueError):
        green_min = DEFAULT_GREEN_MIN
    try:
        yellow_min = Decimal(str(raw.get("yellow_min", DEFAULT_YELLOW_MIN)))
    except (InvalidOperation, TypeError, ValueError):
        yellow_min = DEFAULT_YELLOW_MIN
    if yellow_min < 1 or green_min > 3 or yellow_min >= green_min:
        green_min, yellow_min = DEFAULT_GREEN_MIN, DEFAULT_YELLOW_MIN
    return {"green_min": float(green_min), "yellow_min": float(yellow_min)}


def _band(avg, complete, bands):
    if avg is None:
        return {"key": "UNRATED", "label": "Unrated", "tone": "neutral"}
    if not complete:
        return {"key": "INCOMPLETE", "label": "Incomplete", "tone": "neutral"}
    if avg >= bands["green_min"]:
        return {"key": "GOOD", "label": "Good", "tone": "green"}
    if avg >= bands["yellow_min"]:
        return {"key": "AVERAGE", "label": "Average", "tone": "yellow"}
    return {"key": "UNDERPERFORMING", "label": "Underperforming", "tone": "red"}


def qab_payload(team):
    stats = {int(row["player"]["id"]): row for row in softball_player_stats(team)}
    season_name = team.season_name or ""
    totals = {
        row.player_id: row
        for row in SportsPlayerQABTotal.objects.filter(team=team, season_name=season_name).select_related("player")
    }
    bands = _bands(team)
    players = list(team.players.filter(is_active=True, merged_into__isnull=True).order_by("sort_order", "display_name", "id"))
    rows = []
    team_points = Decimal("0")
    team_pa = 0

    for player in players:
        stat = stats.get(player.id, {})
        pa = int(stat.get("pa") or 0)
        total = totals.get(player.id)
        points = total.points if total else None
        average = round(float(points) / pa, 3) if points is not None and pa > 0 else None
        complete = bool(points is not None and pa > 0 and points >= Decimal(pa) and points <= Decimal(pa * 3))
        if complete:
            team_points += points
            team_pa += pa
        rows.append({
            "player": {
                "id": player.id,
                "display_name": player.display_name,
                "jersey_number": player.jersey_number,
                "primary_position": player.primary_position,
            },
            "season_name": season_name,
            "qab_points": float(points) if points is not None else None,
            "qab_average": average,
            "pa": pa,
            "complete": complete,
            "max_points": pa * 3,
            "band": _band(average, complete, bands),
            "note": total.note if total else "",
            "updated_at": total.updated_at if total else None,
        })

    team_avg = round(float(team_points) / team_pa, 3) if team_pa else None
    return {
        "season_name": season_name,
        "scale": {"poor": 1, "good": 2, "excellent": 3},
        "bands": bands,
        "rows": rows,
        "team": {
            "qab_points": float(team_points),
            "pa": team_pa,
            "qab_average": team_avg,
            "players_complete": sum(1 for row in rows if row["complete"]),
        },
        "definition": "QAB Avg = aggregate 1-3 QAB points divided by all-games PA. 1=Poor, 2=Good, 3=Excellent.",
    }


class WayQABViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def retrieve(self, request, pk=None):
        team = get_object_or_404(SportsTeam.objects.select_related("group"), pk=pk)
        membership = _membership(team, request.user)
        if not membership:
            return Response({"detail": "Active team membership required."}, status=status.HTTP_403_FORBIDDEN)
        payload = qab_payload(team)
        payload["can_manage"] = _can_manage(membership)
        return Response(payload)

    def create(self, request):
        team = get_object_or_404(SportsTeam.objects.select_related("group"), pk=request.data.get("team"))
        membership = _membership(team, request.user)
        if not _can_manage(membership):
            return Response({"detail": "Manager access required."}, status=status.HTTP_403_FORBIDDEN)
        player = get_object_or_404(SportsPlayer, pk=request.data.get("player"), team=team, is_active=True, merged_into__isnull=True)
        try:
            points = Decimal(str(request.data.get("points")))
        except (InvalidOperation, TypeError, ValueError):
            return Response({"detail": "QAB points must be a number."}, status=status.HTTP_400_BAD_REQUEST)
        if points < 0:
            return Response({"detail": "QAB points cannot be negative."}, status=status.HTTP_400_BAD_REQUEST)
        stat = next((row for row in softball_player_stats(team) if int(row["player"]["id"]) == player.id), None)
        pa = int((stat or {}).get("pa") or 0)
        if pa and points > Decimal(pa * 3):
            return Response({"detail": f"QAB points cannot exceed 3 × PA ({pa * 3})."}, status=status.HTTP_400_BAD_REQUEST)
        season_name = str(request.data.get("season_name") or team.season_name or "").strip()[:80]
        row, _ = SportsPlayerQABTotal.objects.update_or_create(
            team=team,
            player=player,
            season_name=season_name,
            defaults={
                "points": points.quantize(Decimal("0.01")),
                "note": str(request.data.get("note") or "Coach-adjusted all-games QAB total").strip()[:240],
                "updated_by": request.user,
            },
        )
        payload = qab_payload(team)
        saved = next((item for item in payload["rows"] if int(item["player"]["id"]) == player.id), None)
        return Response({"saved": saved, "team": payload["team"], "bands": payload["bands"]})

    def partial_update(self, request, pk=None):
        team = get_object_or_404(SportsTeam.objects.select_related("group"), pk=pk)
        membership = _membership(team, request.user)
        if not _can_manage(membership):
            return Response({"detail": "Manager access required."}, status=status.HTTP_403_FORBIDDEN)
        current = _bands(team)
        try:
            green_min = Decimal(str(request.data.get("green_min", current["green_min"])))
            yellow_min = Decimal(str(request.data.get("yellow_min", current["yellow_min"])))
        except (InvalidOperation, TypeError, ValueError):
            return Response({"detail": "Band thresholds must be numbers."}, status=status.HTTP_400_BAD_REQUEST)
        if yellow_min < 1 or green_min > 3 or yellow_min >= green_min:
            return Response({"detail": "Use 1 ≤ yellow threshold < green threshold ≤ 3."}, status=status.HTTP_400_BAD_REQUEST)
        rules = dict(team.badge_rules or {})
        rules["qab_score_bands"] = {"green_min": float(green_min), "yellow_min": float(yellow_min)}
        team.badge_rules = rules
        team.save(update_fields=("badge_rules", "updated_at"))
        return Response({"bands": _bands(team)})
