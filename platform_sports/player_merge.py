"""Manager-only roster cleanup that retains historical statistics and payment records."""
from django.db import transaction
from django.db.models import Q
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import SportsLineupSpot, SportsPlayer, SportsSubstitution, SoftballPlateAppearance
from .ops_models import SoftballStatLedgerEntry, SportsPlayerInvite, SportsPlayerProfile, TeamFeeAssignment


class PlayerMergeMixin:
    @action(detail=True, methods=["post"], url_path="merge")
    @transaction.atomic
    def merge(self, request, pk=None):
        from .views import can_manage_team

        source = self.get_object()
        if not can_manage_team(request.user, source.team):
            return Response({"detail": "Only a team manager can merge roster entries."}, status=status.HTTP_403_FORBIDDEN)
        try:
            target_id = int(request.data.get("target_player") or 0)
        except (TypeError, ValueError):
            return Response({"detail": "Select the roster entry to keep."}, status=status.HTTP_400_BAD_REQUEST)
        if source.pk == target_id:
            return Response({"detail": "Choose two different players."}, status=status.HTTP_400_BAD_REQUEST)
        players = list(
            SportsPlayer.objects.select_for_update()
            .filter(pk__in=[source.pk, target_id], team=source.team, is_active=True)
            .order_by("pk")
        )
        if len(players) != 2:
            return Response({"detail": "Both entries must be active players on the same team."}, status=status.HTTP_400_BAD_REQUEST)
        source = next(player for player in players if player.pk == source.pk)
        target = next(player for player in players if player.pk == target_id)
        if source.user_id and target.user_id and source.user_id != target.user_id:
            return Response({"detail": "Different accounts are linked to these players. Unlink the incorrect account before merging."}, status=status.HTTP_409_CONFLICT)

        source_dues = list(TeamFeeAssignment.objects.select_for_update().filter(player=source))
        target_fee_ids = set(TeamFeeAssignment.objects.filter(player=target).values_list("fee_id", flat=True))
        if any(row.fee_id in target_fee_ids and row.amount_paid_cents for row in source_dues):
            return Response({"detail": "Overlapping fees have recorded payments. Reconcile the duplicate charge before merging."}, status=status.HTTP_409_CONFLICT)

        if source.user_id and not target.user_id:
            target.user_id = source.user_id
            source.user = None
            source.save(update_fields=["user", "updated_at"])
        for field in ("jersey_number", "primary_position", "bats", "throws"):
            if not getattr(target, field) and getattr(source, field):
                setattr(target, field, getattr(source, field))
        target.save()

        try:
            source_profile = source.manager_profile
        except SportsPlayerProfile.DoesNotExist:
            source_profile = None
        if source_profile:
            target_profile, _ = SportsPlayerProfile.objects.get_or_create(player=target)
            for field in ("email", "phone", "profile_photo", "emergency_contact_name", "emergency_contact_phone", "notes"):
                if not getattr(target_profile, field) and getattr(source_profile, field):
                    setattr(target_profile, field, getattr(source_profile, field))
            target_profile.save()

        plate_appearances = SoftballPlateAppearance.objects.filter(player=source).update(player=target)
        manual_stats = SoftballStatLedgerEntry.objects.filter(player=source).update(player=target)
        for assignment in source_dues:
            if assignment.fee_id in target_fee_ids:
                assignment.delete()  # Duplicate unpaid charge; never bill it twice.
            else:
                assignment.player = target
                assignment.save(update_fields=["player", "updated_at"])

        conflicting_lineups = set(SportsLineupSpot.objects.filter(
            player=target, game_id__in=SportsLineupSpot.objects.filter(player=source).values("game_id")
        ).values_list("game_id", flat=True))
        SportsLineupSpot.objects.filter(player=source).exclude(game_id__in=conflicting_lineups).update(player=target)

        conflicting_substitutions = 0
        for sub in SportsSubstitution.objects.filter(Q(outgoing_player=source) | Q(incoming_player=source)):
            new_out = target.pk if sub.outgoing_player_id == source.pk else sub.outgoing_player_id
            new_in = target.pk if sub.incoming_player_id == source.pk else sub.incoming_player_id
            if new_out == new_in:
                conflicting_substitutions += 1
                continue
            sub.outgoing_player_id = new_out
            sub.incoming_player_id = new_in
            sub.save(update_fields=["outgoing_player", "incoming_player"])

        SportsPlayerInvite.objects.filter(player=source, status=SportsPlayerInvite.Status.INVITED).update(
            status=SportsPlayerInvite.Status.REVOKED
        )
        source.is_active = False
        source.merged_into = target
        source.user = None
        source.save(update_fields=["is_active", "merged_into", "user", "updated_at"])
        return Response({
            "merged": True,
            "player": self.get_serializer(target).data,
            "archived_player_id": source.pk,
            "plate_appearances_moved": plate_appearances,
            "stat_entries_moved": manual_stats,
            "historical_lineup_conflicts": len(conflicting_lineups),
            "historical_substitution_conflicts": conflicting_substitutions,
        })

    @action(detail=True, methods=["post"], url_path="delete-empty")
    @transaction.atomic
    def delete_empty(self, request, pk=None):
        """Permanently remove an erroneous empty roster card, never historical data."""
        from .views import can_manage_team

        player = self.get_object()
        if not can_manage_team(request.user, player.team):
            return Response({"detail": "Only a team manager can remove roster entries."}, status=status.HTTP_403_FORBIDDEN)
        if not player.is_active or player.merged_into_id:
            return Response({"detail": "Merged or archived records must be preserved for audit."}, status=status.HTTP_409_CONFLICT)
        if (
            player.plate_appearances.exists() or player.stat_ledger_entries.exists()
            or player.lineup_spots.exists() or player.substitutions_out.exists()
            or player.substitutions_in.exists() or player.fee_assignments.exists()
        ):
            return Response({
                "detail": "This player has game, stats or payment history. Use Merge or Archive to preserve it."
            }, status=status.HTTP_409_CONFLICT)
        player.delete()
        return Response({"deleted": True})
