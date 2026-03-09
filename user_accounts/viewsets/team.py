# user_accounts/viewsets/team.py
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from user_accounts.models import BusinessMember, InviteCode
from user_accounts.permissions import IsBusinessMember, CanManageTeam
from user_accounts.serializers.team import (
    BusinessMemberSerializer,
    InviteCodeSerializer,
    InviteAcceptSerializer,
)


class TeamMembersViewSet(viewsets.ModelViewSet):
    """
    SBO Team: list/update members + permission flags.
    Locked behind: IsBusinessMember + CanManageTeam
    """
    serializer_class = BusinessMemberSerializer
    permission_classes = [IsBusinessMember, CanManageTeam]

    def get_queryset(self):
        return BusinessMember.objects.filter(business_id=self.request.business_id).select_related("user").order_by("-created_at")


class TeamInvitesViewSet(viewsets.ModelViewSet):
    """
    Team Invites: create/list. Accept handled by custom action.
    """
    serializer_class = InviteCodeSerializer
    permission_classes = [IsBusinessMember, CanManageTeam]

    def get_queryset(self):
        return InviteCode.objects.filter(business_id=self.request.business_id).order_by("-created_at")

    def perform_create(self, serializer):
        serializer.save(
            business_id=self.request.business_id,
            created_by=self.request.user,
        )

    @action(detail=False, methods=["post"], url_path="accept", permission_classes=[])
    def accept(self, request):
        """
        POST /api/v1/team/invites/accept/
        Body: { "code": "..." }

        Accepting user becomes BusinessMember for that business,
        with permissions snapshot copied from InviteCode.
        """
        # must be logged in
        if not request.user or not request.user.is_authenticated:
            return Response({"detail": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)

        data = InviteAcceptSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        code = data.validated_data["code"].strip()

        invite = InviteCode.objects.filter(code=code).select_related("business").first()
        if not invite:
            return Response({"detail": "Invalid invite code."}, status=status.HTTP_400_BAD_REQUEST)

        if invite.used_at is not None:
            return Response({"detail": "Invite already used."}, status=status.HTTP_400_BAD_REQUEST)

        if timezone.now() > invite.expires_at:
            return Response({"detail": "Invite expired."}, status=status.HTTP_400_BAD_REQUEST)

        if invite.email and invite.email.lower().strip() != request.user.email.lower().strip():
            return Response({"detail": "Invite is locked to a different email."}, status=status.HTTP_403_FORBIDDEN)

        # Create or update membership
        member, created = BusinessMember.objects.get_or_create(
            business=invite.business,
            user=request.user,
            defaults={
                "role": invite.role,
                "is_active": True,
                "can_manage_team": invite.can_manage_team,
                "can_manage_settings": invite.can_manage_settings,
                "can_view_financials": invite.can_view_financials,
                "can_manage_invoices": invite.can_manage_invoices,
                "can_create_tickets": invite.can_create_tickets,
                "can_assign_tickets": invite.can_assign_tickets,
                "can_close_tickets": invite.can_close_tickets,
                "can_manage_schedule": invite.can_manage_schedule,
                "can_manage_categories": invite.can_manage_categories,
                "can_manage_properties": invite.can_manage_properties,
                "can_manage_connections": invite.can_manage_connections,
            },
        )

        if not created:
            # If they already exist, we "activate" and optionally apply invite perms.
            member.is_active = True
            member.role = invite.role

            member.can_manage_team = invite.can_manage_team
            member.can_manage_settings = invite.can_manage_settings
            member.can_view_financials = invite.can_view_financials
            member.can_manage_invoices = invite.can_manage_invoices
            member.can_create_tickets = invite.can_create_tickets
            member.can_assign_tickets = invite.can_assign_tickets
            member.can_close_tickets = invite.can_close_tickets
            member.can_manage_schedule = invite.can_manage_schedule
            member.can_manage_categories = invite.can_manage_categories
            member.can_manage_properties = invite.can_manage_properties
            member.can_manage_connections = invite.can_manage_connections

            member.save()

        invite.used_at = timezone.now()
        invite.accepted_by = request.user
        invite.save(update_fields=["used_at", "accepted_by"])

        return Response(
            {
                "detail": "Invite accepted.",
                "business_id": invite.business_id,
                "member": BusinessMemberSerializer(member).data,
            },
            status=status.HTTP_200_OK,
        )
