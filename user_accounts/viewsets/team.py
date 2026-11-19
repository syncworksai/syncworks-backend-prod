# user_accounts/viewsets/team.py
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from user_accounts.models import BusinessMember, InviteCode
from user_accounts.permissions import IsBusinessMember, CanManageTeam, _get_active_business_id
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
        return BusinessMember.objects.filter(business_id=_get_active_business_id(self.request, view=self)).select_related("user").order_by("-created_at")

    def perform_update(self, serializer):
        from rest_framework.exceptions import PermissionDenied
        member = self.get_object()
        owner_id = member.business.owner_id
        actor = self.request.user
        privileged = bool(owner_id == actor.id or getattr(actor, "is_superuser", False) or getattr(actor, "is_platform_admin", False))
        if member.user_id == owner_id or str(member.role).upper() == "OWNER":
            raise PermissionDenied("The business owner is managed outside employee permissions.")
        if member.user_id == actor.id:
            raise PermissionDenied("You cannot edit your own employee permissions.")
        values = serializer.validated_data
        role = str(values.get("role", member.role)).upper()
        if role in {"OWNER", "ADMIN", "CEO"}:
            raise PermissionDenied("Cannot grant executive ownership through team management.")
        if not privileged:
            if "role" in values and role not in {"TECH", "TECHNICIAN", "DISPATCH", "ACCOUNTING", "HR"}:
                raise PermissionDenied("Delegated HR cannot assign management roles.")
            for key in ("can_manage_team", "can_manage_settings", "can_view_financials", "can_manage_invoices", "can_manage_connections", "can_manage_properties"):
                if key in values and values[key] != getattr(member, key, False):
                    raise PermissionDenied("Only the owner can edit protected permissions.")
        serializer.save()

    def perform_destroy(self, instance):
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied("Deactivate employee access instead of deleting membership.")

    def perform_create(self, serializer):
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied("Use the employee invite workflow to add team members.")


class TeamInvitesViewSet(viewsets.ModelViewSet):
    """
    Team Invites: create/list. Accept handled by custom action.
    """
    serializer_class = InviteCodeSerializer
    permission_classes = [IsBusinessMember, CanManageTeam]

    def get_queryset(self):
        return InviteCode.objects.filter(business_id=_get_active_business_id(self.request, view=self)).order_by("-created_at")

    def perform_create(self, serializer):
        from rest_framework.exceptions import PermissionDenied
        user = self.request.user
        business_id = _get_active_business_id(self.request, view=self)
        from user_accounts.models import Business
        business = Business.objects.get(pk=business_id)
        owner = business.owner_id == user.id or getattr(user, "is_superuser", False) or getattr(user, "is_platform_admin", False)
        role = str(serializer.validated_data.get("role", "")).upper()
        if role in {"OWNER", "ADMIN", "CEO"}:
            raise PermissionDenied("Owner and platform roles cannot be invited.")
        if not owner:
            if role not in {"TECH", "TECHNICIAN", "DISPATCH", "ACCOUNTING"}:
                raise PermissionDenied("Only the owner may appoint HR or management.")
            protected = ("can_manage_team", "can_manage_settings", "can_view_financials", "can_manage_invoices", "can_manage_connections", "can_manage_properties")
            if any(serializer.validated_data.get(key, False) for key in protected):
                raise PermissionDenied("Only the owner can grant protected permissions.")
        serializer.save(business_id=business_id, created_by=user)

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

        if str(invite.role).upper() in {"OWNER", "ADMIN", "CEO"}:
            return Response({"detail": "This invitation has an invalid executive role."}, status=status.HTTP_403_FORBIDDEN)
        if invite.business.owner_id == request.user.id:
            return Response({"detail": "Business owner access cannot be changed by accepting an employee invitation."}, status=status.HTTP_403_FORBIDDEN)

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
