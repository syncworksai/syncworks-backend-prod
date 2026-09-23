"""Recorded game-situation splits; excludes historical plays missing explicit outs-before."""
from collections import defaultdict

from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from platform_social.models import GroupMembership, SocialGroup
from platform_sports.models import SoftballPlateAppearance, SportsGame, SportsTeam
from .models import SoftballPlayContext


HITS = {"1B", "2B", "3B", "HR"}
AB_EXCLUDED = {"BB", "SF"}


def new_bucket():
    return {"pa": 0, "ab": 0, "h": 0, "rbi": 0, "productive_outs": 0}


def add(bucket, pa, context):
    bucket["pa"] += 1
    if pa.result not in AB_EXCLUDED:
        bucket["ab"] += 1
    if pa.result in HITS:
        bucket["h"] += 1
    bucket["rbi"] += pa.rbi or 0
    if pa.result == "SF" or (context.productive_out and pa.result in ("OUT", "FC", "K")):
        bucket["productive_outs"] += 1


def summarize(bucket):
    return {**bucket, "avg": round(bucket["h"] / bucket["ab"], 3) if bucket["ab"] else None,
            "sample_small": bucket["ab"] < 10}


class GameSituationSplitsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, team_id):
        team = get_object_or_404(SportsTeam.objects.select_related("group"), pk=team_id)
        member = GroupMembership.objects.filter(
            group_id=team.group_id, user=request.user, status=GroupMembership.Status.ACTIVE
        ).exists()
        if not member:
            return Response({"detail": "Join this team to view situation statistics."}, status=status.HTTP_403_FORBIDDEN)
        qs = (
            SoftballPlateAppearance.objects.filter(game__team=team)
            .exclude(game__status=SportsGame.Status.CANCELLED)
            .select_related("advanced_context")
            .order_by("game_id", "sequence")
        )
        player_param = request.query_params.get("player")
        if player_param:
            try:
                player_id = int(player_param)
            except (TypeError, ValueError):
                return Response({"detail": "Choose a valid player ID."}, status=status.HTTP_400_BAD_REQUEST)
            if not team.players.filter(pk=player_id).exists():
                return Response({"detail": "This player is not on the team."}, status=status.HTTP_404_NOT_FOUND)
            qs = qs.filter(player_id=player_id)

        splits = {key: new_bucket() for key in ("0_OUTS", "1_OUT", "2_OUTS", "RISP", "RUNNER_ON")}
        opportunities = {"MOVE_RUNNER": {"attempts": 0, "successes": 0},
                         "SAC_FLY": {"attempts": 0, "successes": 0}}
        tracked = 0
        missing = 0
        for pa in qs:
            try:
                context = pa.advanced_context
            except SoftballPlayContext.DoesNotExist:
                missing += 1
                continue
            if context.outs_before is None:
                missing += 1
                continue
            tracked += 1
            add(splits[("0_OUTS", "1_OUT", "2_OUTS")[context.outs_before]], pa, context)
            risp = context.runner_on_second_before or context.runner_on_third_before
            runner_on = context.runner_on_first_before or risp
            if risp:
                add(splits["RISP"], pa, context)
            if runner_on:
                add(splits["RUNNER_ON"], pa, context)
                opportunities["MOVE_RUNNER"]["attempts"] += 1
                if context.runners_advanced > 0 or (pa.result == "SF" and pa.runs_scored):
                    opportunities["MOVE_RUNNER"]["successes"] += 1
            if context.runner_on_third_before and context.outs_before < 2:
                opportunities["SAC_FLY"]["attempts"] += 1
                if pa.result == "SF" and pa.runs_scored > 0:
                    opportunities["SAC_FLY"]["successes"] += 1

        for metric in opportunities.values():
            metric["rate"] = round(metric["successes"] / metric["attempts"], 3) if metric["attempts"] else None
            metric["sample_small"] = metric["attempts"] < 10

        return Response({
            "team": team.id,
            "player": int(player_param) if player_param else None,
            "tracked_appearances": tracked,
            "excluded_missing_outs_context": missing,
            "splits": {key: summarize(value) for key, value in splits.items()},
            "objectives": opportunities,
            "note": "Only plays with recorded pre-pitch outs are included. Practice and live game records remain separate.",
        })
