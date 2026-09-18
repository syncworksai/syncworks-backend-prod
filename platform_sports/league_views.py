from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from platform_social.models import GroupMembership

from .league_models import (
    LeagueDivision,
    LeagueRosterEntry,
    LeagueSeason,
    LeagueTeamEntry,
    SportsOrganization,
    SportsOrganizationMembership,
    SportsPlayerIdentity,
    SoftballRuleSet,
)
from .league_serializers import (
    LeagueDivisionSerializer,
    LeagueRosterEntrySerializer,
    LeagueSeasonSerializer,
    LeagueTeamEntrySerializer,
    SportsOrganizationMembershipSerializer,
    SportsOrganizationSerializer,
    SportsPlayerIdentitySerializer,
    SoftballRuleSetSerializer,
)
from .models import SportsPlayer
from .views import can_manage_team

User = get_user_model()
ORG_MANAGEMENT_ROLES = (
    SportsOrganizationMembership.Role.COMMISSIONER,
    SportsOrganizationMembership.Role.ADMIN,
)


def can_manage_organization(user, organization):
    return SportsOrganizationMembership.objects.filter(
        organization=organization,
        user=user,
        status=SportsOrganizationMembership.Status.ACTIVE,
        role__in=ORG_MANAGEMENT_ROLES,
    ).exists()


def can_manage_division(user, division):
    return can_manage_organization(user, division.season.organization)


def user_can_view_organization(user, organization):
    if organization.is_public:
        return True
    return SportsOrganizationMembership.objects.filter(
        organization=organization,
        user=user,
        status=SportsOrganizationMembership.Status.ACTIVE,
    ).exists()


def unique_org_slug(name):
    base = slugify(name)[:175] or "league"
    slug = base
    number = 2
    while SportsOrganization.objects.filter(slug=slug).exists():
        slug = f"{base}-{number}"
        number += 1
    return slug


class SportsOrganizationViewSet(viewsets.ModelViewSet):
    serializer_class = SportsOrganizationSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        return SportsOrganization.objects.filter(
            Q(is_public=True)
            | Q(memberships__user=self.request.user, memberships__status=SportsOrganizationMembership.Status.ACTIVE)
        ).distinct().prefetch_related("memberships", "seasons")

    @transaction.atomic
    def perform_create(self, serializer):
        name = serializer.validated_data["name"]
        if not serializer.validated_data.get("slug"):
            serializer.validated_data["slug"] = unique_org_slug(name)
        organization = serializer.save(created_by=self.request.user)
        SportsOrganizationMembership.objects.create(
            organization=organization,
            user=self.request.user,
            role=SportsOrganizationMembership.Role.COMMISSIONER,
            status=SportsOrganizationMembership.Status.ACTIVE,
            invited_by=self.request.user,
        )

    def perform_update(self, serializer):
        organization = self.get_object()
        if not can_manage_organization(self.request.user, organization):
            raise serializers.ValidationError("Commissioner or league admin access is required.")
        serializer.save()

    @action(detail=True, methods=["get"])
    def dashboard(self, request, pk=None):
        organization = self.get_object()
        seasons = organization.seasons.prefetch_related("divisions__team_entries", "divisions__roster_entries")
        current = seasons.filter(is_current=True).first() or seasons.filter(status=LeagueSeason.Status.ACTIVE).first()
        divisions = current.divisions.all() if current else LeagueDivision.objects.none()
        return Response({
            "organization": self.get_serializer(organization).data,
            "current_season": LeagueSeasonSerializer(current).data if current else None,
            "divisions": LeagueDivisionSerializer(divisions, many=True).data,
            "team_count": LeagueTeamEntry.objects.filter(division__season__organization=organization, status=LeagueTeamEntry.Status.ACTIVE).values("team_id").distinct().count(),
            "active_roster_count": LeagueRosterEntry.objects.filter(division__season__organization=organization, status=LeagueRosterEntry.Status.ACTIVE).count(),
            "can_manage": can_manage_organization(request.user, organization),
        })


class SportsOrganizationMembershipViewSet(viewsets.ModelViewSet):
    serializer_class = SportsOrganizationMembershipSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        return SportsOrganizationMembership.objects.filter(
            Q(user=self.request.user)
            | Q(organization__memberships__user=self.request.user,
                organization__memberships__status=SportsOrganizationMembership.Status.ACTIVE,
                organization__memberships__role__in=ORG_MANAGEMENT_ROLES)
        ).select_related("organization", "user", "invited_by").distinct()

    def perform_create(self, serializer):
        organization = serializer.validated_data["organization"]
        if not can_manage_organization(self.request.user, organization):
            raise serializers.ValidationError("Commissioner or league admin access is required.")
        serializer.save(invited_by=self.request.user)

    def perform_update(self, serializer):
        membership = self.get_object()
        if not can_manage_organization(self.request.user, membership.organization):
            raise serializers.ValidationError("Commissioner or league admin access is required.")
        serializer.save()


class LeagueSeasonViewSet(viewsets.ModelViewSet):
    serializer_class = LeagueSeasonSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = LeagueSeason.objects.filter(
            Q(organization__is_public=True)
            | Q(organization__memberships__user=self.request.user, organization__memberships__status=SportsOrganizationMembership.Status.ACTIVE)
        ).select_related("organization", "created_by").prefetch_related("divisions").distinct()
        organization_id = self.request.query_params.get("organization")
        return queryset.filter(organization_id=organization_id) if organization_id else queryset

    @transaction.atomic
    def perform_create(self, serializer):
        organization = serializer.validated_data["organization"]
        if not can_manage_organization(self.request.user, organization):
            raise serializers.ValidationError("Commissioner or league admin access is required.")
        if serializer.validated_data.get("is_current"):
            organization.seasons.update(is_current=False)
        serializer.save(created_by=self.request.user)

    @transaction.atomic
    def perform_update(self, serializer):
        season = self.get_object()
        if not can_manage_organization(self.request.user, season.organization):
            raise serializers.ValidationError("Commissioner or league admin access is required.")
        if serializer.validated_data.get("is_current"):
            season.organization.seasons.exclude(pk=season.pk).update(is_current=False)
        serializer.save()


class LeagueDivisionViewSet(viewsets.ModelViewSet):
    serializer_class = LeagueDivisionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = LeagueDivision.objects.filter(
            Q(season__organization__is_public=True)
            | Q(season__organization__memberships__user=self.request.user,
                season__organization__memberships__status=SportsOrganizationMembership.Status.ACTIVE)
        ).select_related("season__organization").prefetch_related("team_entries", "roster_entries").distinct()
        season_id = self.request.query_params.get("season")
        return queryset.filter(season_id=season_id) if season_id else queryset

    def perform_create(self, serializer):
        season = serializer.validated_data["season"]
        if not can_manage_organization(self.request.user, season.organization):
            raise serializers.ValidationError("Commissioner or league admin access is required.")
        serializer.save()

    def perform_update(self, serializer):
        division = self.get_object()
        if not can_manage_division(self.request.user, division):
            raise serializers.ValidationError("Commissioner or league admin access is required.")
        if "season" in serializer.validated_data and serializer.validated_data["season"].organization_id != division.season.organization_id:
            raise serializers.ValidationError({"season": "Division cannot be moved to another organization."})
        serializer.save()


class LeagueTeamEntryViewSet(viewsets.ModelViewSet):
    serializer_class = LeagueTeamEntrySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = LeagueTeamEntry.objects.filter(
            Q(division__season__organization__is_public=True)
            | Q(division__season__organization__memberships__user=self.request.user,
                division__season__organization__memberships__status=SportsOrganizationMembership.Status.ACTIVE)
            | Q(team__group__memberships__user=self.request.user, team__group__memberships__status=GroupMembership.Status.ACTIVE)
        ).select_related("division__season__organization", "team__group").distinct()
        division_id = self.request.query_params.get("division")
        return queryset.filter(division_id=division_id) if division_id else queryset

    def perform_create(self, serializer):
        division = serializer.validated_data["division"]
        if not can_manage_division(self.request.user, division):
            raise serializers.ValidationError("Commissioner or league admin access is required to add teams.")
        entry = serializer.save()
        entry.full_clean()

    def perform_update(self, serializer):
        entry = self.get_object()
        if not can_manage_division(self.request.user, entry.division):
            raise serializers.ValidationError("Commissioner or league admin access is required.")
        serializer.save()


class LeagueRosterEntryViewSet(viewsets.ModelViewSet):
    serializer_class = LeagueRosterEntrySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = LeagueRosterEntry.objects.filter(
            Q(division__season__organization__is_public=True)
            | Q(division__season__organization__memberships__user=self.request.user,
                division__season__organization__memberships__status=SportsOrganizationMembership.Status.ACTIVE)
            | Q(team__group__memberships__user=self.request.user, team__group__memberships__status=GroupMembership.Status.ACTIVE)
            | Q(identity__user=self.request.user)
        ).select_related("division__season__organization", "team__group", "identity__user", "sports_player").distinct()
        division_id = self.request.query_params.get("division")
        team_id = self.request.query_params.get("team")
        if division_id:
            queryset = queryset.filter(division_id=division_id)
        if team_id:
            queryset = queryset.filter(team_id=team_id)
        return queryset

    def _can_manage_roster(self, user, division, team):
        return can_manage_division(user, division) or can_manage_team(user, team)

    @action(detail=False, methods=["post"], url_path="invite-email")
    @transaction.atomic
    def invite_email(self, request):
        division = get_object_or_404(LeagueDivision.objects.select_related("season__organization"), pk=request.data.get("division"))
        team_entry = get_object_or_404(
            LeagueTeamEntry.objects.select_related("team__group"),
            division=division,
            team_id=request.data.get("team"),
            status=LeagueTeamEntry.Status.ACTIVE,
        )
        team = team_entry.team
        if not self._can_manage_roster(request.user, division, team):
            return Response({"detail": "League admin or team manager access is required."}, status=status.HTTP_403_FORBIDDEN)

        email = str(request.data.get("email") or "").strip().lower()
        if not email or "@" not in email:
            return Response({"email": "Enter a valid player email."}, status=status.HTTP_400_BAD_REQUEST)
        display_name = str(request.data.get("display_name") or "").strip()
        jersey_number = str(request.data.get("jersey_number") or "").strip()

        if division.max_roster_size:
            current = LeagueRosterEntry.objects.filter(
                division=division,
                team=team,
                status__in=(LeagueRosterEntry.Status.INVITED, LeagueRosterEntry.Status.ACTIVE),
            ).count()
            existing = LeagueRosterEntry.objects.filter(division=division, team=team, identity__email=email).exists()
            if current >= division.max_roster_size and not existing:
                return Response({"detail": f"Roster limit of {division.max_roster_size} has been reached."}, status=status.HTTP_400_BAD_REQUEST)

        identity, _ = SportsPlayerIdentity.objects.get_or_create(
            email=email,
            defaults={"display_name": display_name},
        )
        if display_name and not identity.display_name:
            identity.display_name = display_name
            identity.save(update_fields=("display_name", "updated_at"))

        matched_user = User.objects.filter(email__iexact=email).first()
        if matched_user and not identity.user_id:
            identity.claim(matched_user)

        player = None
        if identity.user_id:
            player, _ = SportsPlayer.objects.get_or_create(
                team=team,
                user=identity.user,
                defaults={
                    "display_name": identity.display_name or identity.email,
                    "jersey_number": jersey_number,
                    "created_by": request.user,
                },
            )
            GroupMembership.objects.get_or_create(
                group=team.group,
                user=identity.user,
                defaults={
                    "role": GroupMembership.Role.MEMBER,
                    "status": GroupMembership.Status.ACTIVE,
                    "invited_by": request.user,
                },
            )

        roster, created = LeagueRosterEntry.objects.get_or_create(
            division=division,
            team=team,
            identity=identity,
            defaults={
                "sports_player": player,
                "jersey_number": jersey_number,
                "status": LeagueRosterEntry.Status.ACTIVE if identity.user_id else LeagueRosterEntry.Status.INVITED,
                "accepted_at": timezone.now() if identity.user_id else None,
                "invited_by": request.user,
            },
        )
        if not created:
            roster.jersey_number = jersey_number or roster.jersey_number
            roster.sports_player = player or roster.sports_player
            if identity.user_id:
                roster.status = LeagueRosterEntry.Status.ACTIVE
                roster.accepted_at = roster.accepted_at or timezone.now()
            elif roster.status == LeagueRosterEntry.Status.REMOVED:
                roster.status = LeagueRosterEntry.Status.INVITED
            roster.invited_by = request.user
            roster.invited_at = timezone.now()
            roster.save()

        return Response(self.get_serializer(roster).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="claim-mine")
    @transaction.atomic
    def claim_mine(self, request):
        email = str(getattr(request.user, "email", "") or "").strip().lower()
        if not email:
            return Response({"detail": "Your SyncWorks account needs an email address."}, status=status.HTTP_400_BAD_REQUEST)
        identity = SportsPlayerIdentity.objects.filter(email=email).first()
        if not identity:
            return Response({"claimed": 0, "detail": "No pending sports roster invitations match this email."})
        try:
            identity.claim(request.user)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        claimed = []
        for roster in identity.roster_entries.select_related("team__group", "division").exclude(status=LeagueRosterEntry.Status.REMOVED):
            player, _ = SportsPlayer.objects.get_or_create(
                team=roster.team,
                user=request.user,
                defaults={
                    "display_name": identity.display_name or email,
                    "jersey_number": roster.jersey_number,
                    "created_by": roster.invited_by or request.user,
                },
            )
            GroupMembership.objects.get_or_create(
                group=roster.team.group,
                user=request.user,
                defaults={
                    "role": GroupMembership.Role.MEMBER,
                    "status": GroupMembership.Status.ACTIVE,
                    "invited_by": roster.invited_by,
                },
            )
            roster.sports_player = player
            roster.status = LeagueRosterEntry.Status.ACTIVE
            roster.accepted_at = roster.accepted_at or timezone.now()
            roster.save(update_fields=("sports_player", "status", "accepted_at", "updated_at"))
            claimed.append(roster)
        return Response({"claimed": len(claimed), "rosters": self.get_serializer(claimed, many=True).data})

    def perform_update(self, serializer):
        roster = self.get_object()
        if not self._can_manage_roster(self.request.user, roster.division, roster.team):
            raise serializers.ValidationError("League admin or team manager access is required.")
        serializer.save()

    def perform_destroy(self, instance):
        if not self._can_manage_roster(self.request.user, instance.division, instance.team):
            raise serializers.ValidationError("League admin or team manager access is required.")
        instance.status = LeagueRosterEntry.Status.REMOVED
        instance.save(update_fields=("status", "updated_at"))


class SoftballRuleSetViewSet(viewsets.ModelViewSet):
    serializer_class = SoftballRuleSetSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = SoftballRuleSet.objects.filter(
            Q(organization__is_public=True)
            | Q(
                organization__memberships__user=self.request.user,
                organization__memberships__status=SportsOrganizationMembership.Status.ACTIVE,
            )
        ).select_related("organization", "season", "division", "created_by").distinct()
        organization_id = self.request.query_params.get("organization")
        season_id = self.request.query_params.get("season")
        division_id = self.request.query_params.get("division")
        competition_type = self.request.query_params.get("competition_type")
        if organization_id:
            queryset = queryset.filter(organization_id=organization_id)
        if season_id:
            queryset = queryset.filter(Q(season_id=season_id) | Q(season__isnull=True))
        if division_id:
            queryset = queryset.filter(Q(division_id=division_id) | Q(division__isnull=True))
        if competition_type:
            queryset = queryset.filter(competition_type=competition_type)
        return queryset

    def perform_create(self, serializer):
        organization = serializer.validated_data["organization"]
        if not can_manage_organization(self.request.user, organization):
            raise serializers.ValidationError("Commissioner or league admin access is required.")
        rules = serializer.save(created_by=self.request.user)
        rules.full_clean()

    def perform_update(self, serializer):
        rules = self.get_object()
        if not can_manage_organization(self.request.user, rules.organization):
            raise serializers.ValidationError("Commissioner or league admin access is required.")
        saved = serializer.save()
        saved.full_clean()


class SportsPlayerIdentityViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = SportsPlayerIdentitySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return SportsPlayerIdentity.objects.filter(
            Q(user=self.request.user)
            | Q(roster_entries__team__group__memberships__user=self.request.user,
                roster_entries__team__group__memberships__status=GroupMembership.Status.ACTIVE)
            | Q(roster_entries__division__season__organization__memberships__user=self.request.user,
                roster_entries__division__season__organization__memberships__status=SportsOrganizationMembership.Status.ACTIVE)
        ).select_related("user").distinct()
