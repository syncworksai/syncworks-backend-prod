from __future__ import annotations

from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from platform_social.models import GroupMembership

from .models import SoftballPlateAppearance, SportsGame, SportsPlayer, SportsTeam
from .ops_models import (
    SoftballStatLedgerEntry,
    SportsPlayerProfile,
    TeamFee,
    TeamFeeAssignment,
    TeamPaymentSettings,
)
from .ops_serializers import (
    SoftballStatLedgerEntrySerializer,
    SportsPlayerProfileSerializer,
    TeamFeeAssignmentSerializer,
    TeamFeeSerializer,
    TeamPaymentSettingsSerializer,
)
from .serializers import SportsPlayerSerializer
from .views import AB_EXCLUDED_RESULTS, HIT_RESULTS, active_group_ids, can_manage_team, user_can_access_team


MANAGEMENT_ROLES = (
    GroupMembership.Role.OWNER,
    GroupMembership.Role.DIRECTOR,
    GroupMembership.Role.MANAGER,
)


def managed_group_ids(user):
    return GroupMembership.objects.filter(
        user=user,
        status=GroupMembership.Status.ACTIVE,
        role__in=MANAGEMENT_ROLES,
    ).values_list("group_id", flat=True)


def _ratio(numerator, denominator):
    return round(numerator / denominator, 3) if denominator else 0.0


def _scope_game_types(scope):
    scope = str(scope or "ALL").upper()
    if scope == "LEAGUE":
        return (SportsGame.GameType.LEAGUE,)
    if scope == "TOURNAMENT":
        return (SportsGame.GameType.TOURNAMENT,)
    return (SportsGame.GameType.LEAGUE, SportsGame.GameType.TOURNAMENT)


def softball_stats_summary(team, scope="ALL"):
    scope = str(scope or "ALL").upper()
    if scope not in ("ALL", "LEAGUE", "TOURNAMENT"):
        scope = "ALL"
    players = list(team.players.order_by("sort_order", "display_name", "id"))
    rows = {
        player.id: {
            "player": SportsPlayerSerializer(player).data,
            "game_ids": set(),
            "manual_games": 0,
            "pa": 0,
            "ab": 0,
            "h": 0,
            "single": 0,
            "double": 0,
            "triple": 0,
            "hr": 0,
            "bb": 0,
            "sf": 0,
            "rbi": 0,
            "runs": 0,
            "tb": 0,
        }
        for player in players
    }

    appearances = SoftballPlateAppearance.objects.filter(
        game__team=team,
        game__game_type__in=_scope_game_types(scope),
    ).exclude(game__status=SportsGame.Status.CANCELLED).select_related("player", "game")
    for pa in appearances:
        row = rows.setdefault(pa.player_id, {
            "player": SportsPlayerSerializer(pa.player).data,
            "game_ids": set(), "manual_games": 0, "pa": 0, "ab": 0, "h": 0,
            "single": 0, "double": 0, "triple": 0, "hr": 0, "bb": 0, "sf": 0,
            "rbi": 0, "runs": 0, "tb": 0,
        })
        row["game_ids"].add(pa.game_id)
        row["pa"] += 1
        row["rbi"] += pa.rbi
        row["runs"] += pa.runs_scored
        if pa.result not in AB_EXCLUDED_RESULTS:
            row["ab"] += 1
        if pa.result in HIT_RESULTS:
            row["h"] += 1
        if pa.result == SoftballPlateAppearance.Result.SINGLE:
            row["single"] += 1
            row["tb"] += 1
        elif pa.result == SoftballPlateAppearance.Result.DOUBLE:
            row["double"] += 1
            row["tb"] += 2
        elif pa.result == SoftballPlateAppearance.Result.TRIPLE:
            row["triple"] += 1
            row["tb"] += 3
        elif pa.result == SoftballPlateAppearance.Result.HOME_RUN:
            row["hr"] += 1
            row["tb"] += 4
        elif pa.result == SoftballPlateAppearance.Result.WALK:
            row["bb"] += 1
        elif pa.result == SoftballPlateAppearance.Result.SAC_FLY:
            row["sf"] += 1

    ledger = team.stat_ledger_entries.select_related("player")
    if scope in ("LEAGUE", "TOURNAMENT"):
        ledger = ledger.filter(scope=scope)
    else:
        ledger = ledger.filter(scope__in=(SoftballStatLedgerEntry.Scope.LEAGUE, SoftballStatLedgerEntry.Scope.TOURNAMENT))
    for entry in ledger:
        row = rows.setdefault(entry.player_id, {
            "player": SportsPlayerSerializer(entry.player).data,
            "game_ids": set(), "manual_games": 0, "pa": 0, "ab": 0, "h": 0,
            "single": 0, "double": 0, "triple": 0, "hr": 0, "bb": 0, "sf": 0,
            "rbi": 0, "runs": 0, "tb": 0,
        })
        singles = max(0, entry.hits - entry.doubles - entry.triples - entry.home_runs)
        row["manual_games"] += entry.games
        row["pa"] += entry.pa
        row["ab"] += entry.ab
        row["h"] += entry.hits
        row["single"] += singles
        row["double"] += entry.doubles
        row["triple"] += entry.triples
        row["hr"] += entry.home_runs
        row["bb"] += entry.walks
        row["sf"] += entry.sac_flies
        row["rbi"] += entry.rbi
        row["runs"] += entry.runs
        row["tb"] += singles + (entry.doubles * 2) + (entry.triples * 3) + (entry.home_runs * 4)

    output = []
    for row in rows.values():
        row["g"] = len(row.pop("game_ids")) + row.pop("manual_games")
        row["avg"] = _ratio(row["h"], row["ab"])
        row["obp"] = _ratio(row["h"] + row["bb"], row["ab"] + row["bb"] + row["sf"])
        row["slg"] = _ratio(row["tb"], row["ab"])
        row["ops"] = round(row["obp"] + row["slg"], 3)
        output.append(row)
    output.sort(key=lambda row: (-(row["ops"] or 0), -(row["avg"] or 0), row["player"]["display_name"]))
    return output


class SportsPlayerProfileViewSet(viewsets.ModelViewSet):
    serializer_class = SportsPlayerProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        manager_groups = managed_group_ids(self.request.user)
        queryset = SportsPlayerProfile.objects.filter(
            Q(player__team__group_id__in=manager_groups) | Q(player__user=self.request.user)
        ).select_related("player__team__group", "player__user").distinct()
        team_id = self.request.query_params.get("team")
        player_id = self.request.query_params.get("player")
        if team_id:
            queryset = queryset.filter(player__team_id=team_id)
        if player_id:
            queryset = queryset.filter(player_id=player_id)
        return queryset

    def perform_create(self, serializer):
        player = serializer.validated_data["player"]
        if not can_manage_team(self.request.user, player.team):
            raise serializers.ValidationError("You do not manage this sports team.")
        serializer.save()

    def perform_update(self, serializer):
        profile = self.get_object()
        if not can_manage_team(self.request.user, profile.player.team):
            raise serializers.ValidationError("You do not manage this sports team.")
        if "player" in serializer.validated_data and serializer.validated_data["player"].id != profile.player_id:
            raise serializers.ValidationError({"player": "A profile cannot be moved to another player."})
        serializer.save()

    def perform_destroy(self, instance):
        if not can_manage_team(self.request.user, instance.player.team):
            raise serializers.ValidationError("You do not manage this sports team.")
        instance.delete()


class TeamPaymentSettingsViewSet(viewsets.ModelViewSet):
    serializer_class = TeamPaymentSettingsSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        queryset = TeamPaymentSettings.objects.filter(team__group_id__in=active_group_ids(self.request.user)).select_related("team__group")
        team_id = self.request.query_params.get("team")
        return queryset.filter(team_id=team_id) if team_id else queryset

    def perform_create(self, serializer):
        team = serializer.validated_data["team"]
        if not can_manage_team(self.request.user, team):
            raise serializers.ValidationError("You do not manage this sports team.")
        serializer.save(platform_fee_bps=100, free_mode=True)

    def perform_update(self, serializer):
        settings = self.get_object()
        if not can_manage_team(self.request.user, settings.team):
            raise serializers.ValidationError("You do not manage this sports team.")
        serializer.save(platform_fee_bps=100, free_mode=True)

    @action(detail=False, methods=["post"])
    def ensure(self, request):
        team = get_object_or_404(SportsTeam, pk=request.data.get("team"))
        if not can_manage_team(request.user, team):
            return Response({"detail": "You do not manage this sports team."}, status=status.HTTP_403_FORBIDDEN)
        settings, _ = TeamPaymentSettings.objects.get_or_create(team=team)
        return Response(self.get_serializer(settings).data)


class TeamFeeViewSet(viewsets.ModelViewSet):
    serializer_class = TeamFeeSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        manager_groups = managed_group_ids(self.request.user)
        queryset = TeamFee.objects.filter(
            Q(team__group_id__in=manager_groups) | Q(assignments__player__user=self.request.user)
        ).select_related("team__group", "created_by").prefetch_related("assignments").distinct()
        team_id = self.request.query_params.get("team")
        return queryset.filter(team_id=team_id) if team_id else queryset

    def perform_create(self, serializer):
        team = serializer.validated_data["team"]
        if not can_manage_team(self.request.user, team):
            raise serializers.ValidationError("You do not manage this sports team.")
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        fee = self.get_object()
        if not can_manage_team(self.request.user, fee.team):
            raise serializers.ValidationError("You do not manage this sports team.")
        serializer.save()

    def perform_destroy(self, instance):
        if not can_manage_team(self.request.user, instance.team):
            raise serializers.ValidationError("You do not manage this sports team.")
        instance.is_active = False
        instance.save(update_fields=("is_active", "updated_at"))

    @action(detail=True, methods=["post"], url_path="assign-roster")
    def assign_roster(self, request, pk=None):
        fee = self.get_object()
        if not can_manage_team(request.user, fee.team):
            return Response({"detail": "You do not manage this sports team."}, status=status.HTTP_403_FORBIDDEN)
        players = SportsPlayer.objects.filter(team=fee.team, is_active=True)
        created = 0
        for player in players:
            _, was_created = TeamFeeAssignment.objects.get_or_create(
                fee=fee,
                player=player,
                defaults={"amount_cents": fee.amount_cents, "updated_by": request.user},
            )
            created += int(was_created)
        return Response({"assigned": players.count(), "created": created})


class TeamFeeAssignmentViewSet(viewsets.ModelViewSet):
    serializer_class = TeamFeeAssignmentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        manager_groups = managed_group_ids(self.request.user)
        queryset = TeamFeeAssignment.objects.filter(
            Q(fee__team__group_id__in=manager_groups) | Q(player__user=self.request.user)
        ).select_related("fee__team__group", "player__user", "updated_by").distinct()
        team_id = self.request.query_params.get("team")
        fee_id = self.request.query_params.get("fee")
        if team_id:
            queryset = queryset.filter(fee__team_id=team_id)
        if fee_id:
            queryset = queryset.filter(fee_id=fee_id)
        return queryset

    def perform_create(self, serializer):
        fee = serializer.validated_data["fee"]
        player = serializer.validated_data["player"]
        if not can_manage_team(self.request.user, fee.team):
            raise serializers.ValidationError("You do not manage this sports team.")
        if player.team_id != fee.team_id:
            raise serializers.ValidationError({"player": "Player must belong to this fee's team."})
        serializer.save(updated_by=self.request.user)

    def perform_update(self, serializer):
        assignment = self.get_object()
        if not can_manage_team(self.request.user, assignment.fee.team):
            raise serializers.ValidationError("You do not manage this sports team.")
        serializer.save(updated_by=self.request.user)

    def perform_destroy(self, instance):
        if not can_manage_team(self.request.user, instance.fee.team):
            raise serializers.ValidationError("You do not manage this sports team.")
        instance.delete()


class SoftballStatLedgerEntryViewSet(viewsets.ModelViewSet):
    serializer_class = SoftballStatLedgerEntrySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = SoftballStatLedgerEntry.objects.filter(team__group_id__in=active_group_ids(self.request.user)).select_related("team__group", "player__user", "created_by")
        team_id = self.request.query_params.get("team")
        player_id = self.request.query_params.get("player")
        scope = str(self.request.query_params.get("scope") or "").upper()
        if team_id:
            queryset = queryset.filter(team_id=team_id)
        if player_id:
            queryset = queryset.filter(player_id=player_id)
        if scope in SoftballStatLedgerEntry.Scope.values:
            queryset = queryset.filter(scope=scope)
        return queryset

    def perform_create(self, serializer):
        team = serializer.validated_data["team"]
        if not can_manage_team(self.request.user, team):
            raise serializers.ValidationError("You do not manage this sports team.")
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        entry = self.get_object()
        if not can_manage_team(self.request.user, entry.team):
            raise serializers.ValidationError("You do not manage this sports team.")
        serializer.save()

    def perform_destroy(self, instance):
        if not can_manage_team(self.request.user, instance.team):
            raise serializers.ValidationError("You do not manage this sports team.")
        instance.delete()

    @action(detail=False, methods=["get"])
    def summary(self, request):
        team = get_object_or_404(SportsTeam.objects.select_related("group"), pk=request.query_params.get("team"))
        if not user_can_access_team(request.user, team):
            return Response({"detail": "You cannot access this team."}, status=status.HTTP_403_FORBIDDEN)
        if team.sport != SportsTeam.Sport.SOFTBALL:
            return Response({"detail": "This stat summary is currently for softball."}, status=status.HTTP_400_BAD_REQUEST)
        scope = str(request.query_params.get("scope") or "ALL").upper()
        return Response({"scope": scope if scope in ("ALL", "LEAGUE", "TOURNAMENT") else "ALL", "rows": softball_stats_summary(team, scope)})
