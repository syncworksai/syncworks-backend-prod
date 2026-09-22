from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import SportsGame, SoftballPlateAppearance
from .ops_models import SportsPlayerMoment
from .player_badges import card_progress


class PlayerProgressMixin:
    @action(detail=True, methods=["get"], url_path="badge-card")
    def badge_card(self, request, pk=None):
        player = self.get_object()  # Team membership / visibility enforced by queryset.
        if not player.is_active:
            return Response({"detail": "This card was archived. Open the surviving roster entry."},
                            status=status.HTTP_409_CONFLICT)
        return Response(card_progress(player))

    @action(detail=True, methods=["post"], url_path="verify-moment")
    @transaction.atomic
    def verify_moment(self, request, pk=None):
        from .views import can_score_team

        player = self.get_object()
        if not player.is_active:
            return Response({"detail": "Cannot award moments to an archived player."},
                            status=status.HTTP_409_CONFLICT)
        if not can_score_team(request.user, player.team):
            return Response({"detail": "Only a manager or scorekeeper can verify game moments."},
                            status=status.HTTP_403_FORBIDDEN)
        kind = str(request.data.get("kind") or "").upper().strip()
        if kind not in SportsPlayerMoment.Kind.values:
            return Response({"detail": "Choose a valid achievement event."},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            game_id = int(request.data.get("game") or 0)
        except (TypeError, ValueError):
            return Response({"detail": "Choose a completed game."}, status=status.HTTP_400_BAD_REQUEST)
        game = SportsGame.objects.filter(
            pk=game_id, team=player.team, status=SportsGame.Status.FINAL,
        ).first()
        if not game:
            return Response({"detail": "Select a finalized game from this team."},
                            status=status.HTTP_400_BAD_REQUEST)
        played = game.lineup_spots.filter(player=player).exists() or game.plate_appearances.filter(player=player).exists()
        if not played:
            return Response({"detail": "This player must appear in that game's lineup or recorded plays."},
                            status=status.HTTP_400_BAD_REQUEST)
        appearance = None
        if kind in (SportsPlayerMoment.Kind.TYING_HIT, SportsPlayerMoment.Kind.GO_AHEAD_HIT):
            # A manager verifies whether the hit actually tied or took the lead.
            # The API also requires a late run-producing hit to prevent free-form awards.
            late_inning = max(1, int(game.innings_scheduled or 7) - 2)
            appearance = game.plate_appearances.filter(
                player=player, result__in=("1B", "2B", "3B", "HR"),
                inning__gte=late_inning, rbi__gte=1,
            ).order_by("-inning", "-sequence").first()
            if not appearance:
                return Response({
                    "detail": f"A verified Clutch badge requires a hit with at least one RBI in inning {late_inning} or later. The manager must confirm it actually tied or took the lead."
                }, status=status.HTTP_400_BAD_REQUEST)
        if SportsPlayerMoment.objects.filter(game=game, player=player, kind=kind).exists():
            return Response({"detail": "This achievement was already verified for this player and game."},
                            status=status.HTTP_409_CONFLICT)
        try:
            with transaction.atomic():
                moment = SportsPlayerMoment.objects.create(
                    game=game, player=player, kind=kind,
                    plate_appearance=appearance, verified_by=request.user,
                )
        except IntegrityError:
            return Response({"detail": "This moment has already been verified."},
                            status=status.HTTP_409_CONFLICT)
        return Response({"moment_id": moment.pk, "card": card_progress(player)}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["delete"], url_path=r"moments/(?P<moment_id>[0-9]+)")
    def remove_moment(self, request, pk=None, moment_id=None):
        from .views import can_score_team

        player = self.get_object()
        if not can_score_team(request.user, player.team):
            return Response({"detail": "Only a manager or scorekeeper may correct verified moments."},
                            status=status.HTTP_403_FORBIDDEN)
        moment = player.verified_moments.filter(pk=moment_id).first()
        if not moment:
            return Response({"detail": "Verified moment not found."}, status=status.HTTP_404_NOT_FOUND)
        moment.delete()
        return Response({"removed": True, "card": card_progress(player)})
