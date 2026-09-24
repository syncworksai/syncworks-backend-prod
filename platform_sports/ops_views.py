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
    SportsPracticeSession,
    SportsPracticeRep,
    SportsPlayerAward,
    TeamFee,
    TeamFeeAssignment,
    TeamPaymentSettings,
)
from .ops_serializers import (
    SoftballStatLedgerEntrySerializer,
    SportsPlayerProfileSerializer,
    SportsPracticeSessionSerializer,
    SportsPracticeRepSerializer,
    SportsPlayerAwardSerializer,
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
    players = list(team.players.filter(merged_into__isnull=True).order_by("sort_order", "display_name", "id"))
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
        if not can_manage_team(self.request.user, player.team) and player.user_id != self.request.user.id:
            raise serializers.ValidationError("You may only create your own player profile.")
        serializer.save()

    def perform_update(self, serializer):
        profile = self.get_object()
        manager = can_manage_team(self.request.user, profile.player.team)
        owner = profile.player.user_id == self.request.user.id
        if not manager and not owner:
            raise serializers.ValidationError("You may only edit your own player profile.")
        if "player" in serializer.validated_data and serializer.validated_data["player"].id != profile.player_id:
            raise serializers.ValidationError({"player": "A profile cannot be moved to another player."})
        if owner and not manager:
            serializer.validated_data.pop("notes", None)
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
        previous_amount = fee.amount_cents
        fee = serializer.save()
        if fee.amount_cents != previous_amount:
            for assignment in fee.assignments.exclude(
                status__in=(TeamFeeAssignment.Status.PAID, TeamFeeAssignment.Status.WAIVED)
            ):
                assignment.amount_cents = fee.amount_cents
                if assignment.amount_paid_cents >= fee.amount_cents and fee.amount_cents > 0:
                    assignment.status = TeamFeeAssignment.Status.PAID
                elif assignment.amount_paid_cents > 0:
                    assignment.status = TeamFeeAssignment.Status.PARTIAL
                else:
                    assignment.status = TeamFeeAssignment.Status.DUE
                assignment.updated_by = self.request.user
                assignment.save()

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


class SportsPlayerAwardViewSet(viewsets.ModelViewSet):
    serializer_class = SportsPlayerAwardSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        group_ids = active_group_ids(self.request.user)
        queryset = SportsPlayerAward.objects.filter(
            team__group_id__in=group_ids
        ).select_related("team__group", "player__user", "awarded_by")
        team_id = self.request.query_params.get("team")
        player_id = self.request.query_params.get("player")
        if team_id:
            queryset = queryset.filter(team_id=team_id)
        if player_id:
            queryset = queryset.filter(player_id=player_id)
        return queryset

    def perform_create(self, serializer):
        team = serializer.validated_data["team"]
        if not can_manage_team(self.request.user, team):
            raise serializers.ValidationError("Only a coach or manager can give team awards.")
        serializer.save(awarded_by=self.request.user)

    def perform_update(self, serializer):
        award = self.get_object()
        if not can_manage_team(self.request.user, award.team):
            raise serializers.ValidationError("Only a coach or manager can edit team awards.")
        serializer.save()

    def perform_destroy(self, instance):
        if not can_manage_team(self.request.user, instance.team):
            raise serializers.ValidationError("Only a coach or manager can remove team awards.")
        instance.delete()


class SportsPracticeSessionViewSet(viewsets.ModelViewSet):
    serializer_class = SportsPracticeSessionSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        group_ids = active_group_ids(self.request.user)
        queryset = SportsPracticeSession.objects.filter(
            team__group_id__in=group_ids
        ).select_related("team__group", "player__user", "created_by").prefetch_related("reps")
        team_id = self.request.query_params.get("team")
        player_id = self.request.query_params.get("player")
        if team_id:
            queryset = queryset.filter(team_id=team_id)
        if player_id:
            queryset = queryset.filter(player_id=player_id)
        if not self.request.user.is_staff:
            manager_groups = set(managed_group_ids(self.request.user))
            queryset = queryset.filter(
                Q(team__group_id__in=manager_groups) | Q(player__user=self.request.user)
            )
        return queryset

    def perform_create(self, serializer):
        team = serializer.validated_data["team"]
        player = serializer.validated_data["player"]
        if not can_manage_team(self.request.user, team) and player.user_id != self.request.user.id:
            raise serializers.ValidationError("You may only log your own practice.")
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        session = self.get_object()
        if not can_manage_team(self.request.user, session.team) and session.player.user_id != self.request.user.id:
            raise serializers.ValidationError("You may only edit your own practice.")
        serializer.save()

    def perform_destroy(self, instance):
        if not can_manage_team(self.request.user, instance.team) and instance.player.user_id != self.request.user.id:
            raise serializers.ValidationError("You may only remove your own practice.")
        instance.delete()

    @action(detail=True, methods=["post"], url_path="add-rep")
    def add_rep(self, request, pk=None):
        session = self.get_object()
        if not can_manage_team(request.user, session.team) and session.player.user_id != request.user.id:
            return Response({"detail": "You may only log reps for your own practice."}, status=status.HTTP_403_FORBIDDEN)
        data = request.data.copy()
        data["session"] = session.id
        sequence = (session.reps.order_by("-sequence").values_list("sequence", flat=True).first() or 0) + 1
        serializer = SportsPracticeRepSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save(sequence=sequence)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        try:
            team_id = int(request.query_params.get("team") or 0)
        except (TypeError, ValueError):
            return Response({"detail": "Choose a team."}, status=status.HTTP_400_BAD_REQUEST)
        team = get_object_or_404(SportsTeam, pk=team_id)
        if team.group_id not in set(active_group_ids(request.user)):
            return Response({"detail": "Join this team to view practice."}, status=status.HTTP_403_FORBIDDEN)
        player_id = request.query_params.get("player")
        player = None
        if player_id:
            player = get_object_or_404(SportsPlayer, pk=player_id, team=team)
            if player.user_id != request.user.id and not can_manage_team(request.user, team):
                return Response({"detail": "Only the player or coach can view individual practice analysis."}, status=status.HTTP_403_FORBIDDEN)
        elif not can_manage_team(request.user, team):
            player = SportsPlayer.objects.filter(team=team, user=request.user, is_active=True).first()
            if not player:
                return Response({"detail": "Link your player card first."}, status=status.HTTP_400_BAD_REQUEST)

        sessions = SportsPracticeSession.objects.filter(team=team)
        live = SoftballPlateAppearance.objects.filter(game__team=team).exclude(game__status=SportsGame.Status.CANCELLED)
        if player:
            sessions = sessions.filter(player=player)
            live = live.filter(player=player)
        reps = SportsPracticeRep.objects.filter(session__in=sessions)

        def average(queryset):
            at_bats = queryset.exclude(result__in=("BB", "SF")).count()
            hits = queryset.filter(result__in=("1B","2B","3B","HR")).count()
            return round(hits / at_bats, 3) if at_bats else 0.0, at_bats, hits

        practice_avg, practice_ab, practice_hits = average(reps)
        live_avg, live_ab, live_hits = average(live)
        practice_two_avg, practice_two_ab, _ = average(reps.filter(outs_before=2))
        live_two_avg, live_two_ab, _ = average(live.filter(outs_before=2))
        practice_reps = reps.count()
        live_pa = live.count()
        practice_two_reps = reps.filter(outs_before=2).count()
        live_two_pa = live.filter(outs_before=2).count()

        objectives = []
        for key, label in SportsPracticeRep.Objective.choices:
            p = reps.filter(objective=key)
            p_total = p.count()
            p_success = p.filter(successful=True).count()
            p_avg, p_ab, p_hits = average(p)
            l = live.filter(situation_objective=key)
            l_total = l.count()
            l_success = l.filter(situation_success=True).count()
            l_avg, l_ab, l_hits = average(l)
            objectives.append({
                "key": key,
                "label": label,
                "practice_attempts": p_total,
                "practice_ab": p_ab,
                "practice_hits": p_hits,
                "practice_avg": p_avg,
                "practice_successes": p_success,
                "practice_rate": round(p_success / p_total, 3) if p_total else None,
                "live_attempts": l_total,
                "live_ab": l_ab,
                "live_hits": l_hits,
                "live_avg": l_avg,
                "live_successes": l_success,
                "live_rate": round(l_success / l_total, 3) if l_total else None,
            })

        recommendation = []
        for row in objectives:
            if row["live_attempts"] >= 3 and (row["live_rate"] or 0) < .5:
                recommendation.append({
                    "priority": "HIGH",
                    "objective": row["key"],
                    "title": f"Work on {row['label'].lower()}",
                    "reason": f"Live success is {round((row['live_rate'] or 0)*100)}% over {row['live_attempts']} tracked chances.",
                })
            elif row["practice_attempts"] >= 5 and row["live_attempts"] and row["practice_rate"] is not None and row["live_rate"] is not None and row["practice_rate"] - row["live_rate"] >= .2:
                recommendation.append({
                    "priority": "MEDIUM",
                    "objective": row["key"],
                    "title": f"Transfer {row['label'].lower()} into games",
                    "reason": "Practice success is materially ahead of live-game success.",
                })
        if live_two_ab >= 3 and live_two_avg < live_avg:
            recommendation.append({
                "priority": "MEDIUM", "objective": "TWO_OUT_HIT",
                "title": "Two-out hitting round",
                "reason": f"Two-out AVG {live_two_avg:.3f} trails tracked live AVG {live_avg:.3f}.",
            })

        return Response({
            "player": SportsPlayerSerializer(player).data if player else None,
            "practice": {"avg": practice_avg, "reps": practice_reps, "ab": practice_ab, "hits": practice_hits, "two_out_avg": practice_two_avg, "two_out_reps": practice_two_reps, "two_out_ab": practice_two_ab},
            "live": {"avg": live_avg, "pa": live_pa, "ab": live_ab, "hits": live_hits, "two_out_avg": live_two_avg, "two_out_pa": live_two_pa, "two_out_ab": live_two_ab},
            "objectives": objectives,
            "recommendations": recommendation[:5],
            "tracking_note": "Live comparisons only include plate appearances where the Game Book scorer recorded situation context.",
        })


class SportsPracticeRepViewSet(viewsets.ModelViewSet):
    serializer_class = SportsPracticeRepSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self):
        group_ids = active_group_ids(self.request.user)
        queryset = SportsPracticeRep.objects.filter(session__team__group_id__in=group_ids).select_related("session__team", "session__player")
        session_id = self.request.query_params.get("session")
        if session_id:
            queryset = queryset.filter(session_id=session_id)
        manager_groups = set(managed_group_ids(self.request.user))
        return queryset.filter(Q(session__team__group_id__in=manager_groups) | Q(session__player__user=self.request.user))

    def perform_update(self, serializer):
        rep = self.get_object()
        if not can_manage_team(self.request.user, rep.session.team) and rep.session.player.user_id != self.request.user.id:
            raise serializers.ValidationError("You may only edit your own practice rep.")
        serializer.save()

    def perform_destroy(self, instance):
        if not can_manage_team(self.request.user, instance.session.team) and instance.session.player.user_id != self.request.user.id:
            raise serializers.ValidationError("You may only remove your own practice rep.")
        instance.delete()
