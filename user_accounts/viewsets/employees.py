from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from user_accounts.models import Business, BusinessMember
from user_accounts.permissions import (
    IsAuthenticated,
    IsSboOrPlatformOwner,
    CanManageTeamForBusiness,
)
from user_accounts.serializers.employees import (
    BusinessMemberSerializer,
    EmployeeInviteCreateSerializer,
    EmployeeInviteResponseSerializer,
    EmployeeInviteAcceptSerializer,
)
from user_accounts.services.employees import invite_employee, accept_employee_invite, terminate_member


class BusinessTeamViewSet(viewsets.ViewSet):
    """
    Routes:
      POST /businesses/{id}/invite-employee/
      GET  /businesses/{id}/members/
    """

    permission_classes = [IsAuthenticated, IsSboOrPlatformOwner]

    def _get_business(self, pk: int) -> Business:
        return Business.objects.get(pk=pk)

    @action(detail=True, methods=["post"], url_path="invite-employee", permission_classes=[IsAuthenticated, IsSboOrPlatformOwner, CanManageTeamForBusiness])
    def invite_employee(self, request, pk=None):
        business = self._get_business(pk)
        ser = EmployeeInviteCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        res = invite_employee(
            business=business,
            invited_by=request.user,
            email=ser.validated_data["email"],
            seat_role=ser.validated_data["role"],
            permissions=ser.validated_data.get("permissions") or None,
        )
        return Response(EmployeeInviteResponseSerializer(res.invite).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="members", permission_classes=[IsAuthenticated, IsSboOrPlatformOwner, CanManageTeamForBusiness])
    def members(self, request, pk=None):
        business = self._get_business(pk)
        qs = BusinessMember.objects.filter(business=business).select_related("user").order_by("id")
        return Response(BusinessMemberSerializer(qs, many=True).data, status=status.HTTP_200_OK)


class BusinessMemberViewSet(viewsets.ModelViewSet):
    """
    Routes:
      PATCH /business-members/{id}/  (toggle permissions/role/is_active)
      POST  /business-members/{id}/terminate/
    """

    queryset = BusinessMember.objects.select_related("user", "business").all()
    serializer_class = BusinessMemberSerializer
    permission_classes = [IsAuthenticated, IsSboOrPlatformOwner]

    def partial_update(self, request, *args, **kwargs):
        member = self.get_object()

        # Must be able to manage that business
        CanManageTeamForBusiness().check_object_permission(request, self, member.business)

        # Allowed editable fields
        allowed = {
            "role",
            "is_active",
            "can_view_invoices",
            "can_send_quotes",
            "can_assign_tickets",
            "can_manage_team",
            "can_post_internal_messages",
        }
        payload = {k: v for k, v in request.data.items() if k in allowed}

        for k, v in payload.items():
            setattr(member, k, v)

        if payload.get("is_active") is False and member.terminated_at is None:
            # If they are deactivated via patch, mark terminated_at
            terminate_member(member=member, terminated_by=request.user)

        member.save()
        return Response(self.get_serializer(member).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="terminate")
    def terminate(self, request, pk=None):
        member = self.get_object()
        CanManageTeamForBusiness().check_object_permission(request, self, member.business)

        terminate_member(member=member, terminated_by=request.user)
        return Response(self.get_serializer(member).data, status=status.HTTP_200_OK)


class EmployeeInviteAcceptViewSet(viewsets.ViewSet):
    """
    Route:
      POST /auth/employee-invites/accept/
    """

    permission_classes = []

    @action(detail=False, methods=["post"], url_path="accept")
    def accept(self, request):
        ser = EmployeeInviteAcceptSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        out = accept_employee_invite(
            code=ser.validated_data["code"],
            first_name=ser.validated_data.get("first_name", ""),
            last_name=ser.validated_data.get("last_name", ""),
            password=ser.validated_data["password"],
        )
        return Response(out, status=status.HTTP_200_OK)
