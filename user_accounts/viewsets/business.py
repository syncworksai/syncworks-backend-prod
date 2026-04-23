from __future__ import annotations

from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models import Business, BusinessMember
from user_accounts.serializers.business import BusinessSerializer, BusinessMemberSerializer
from user_accounts.serializers.employees import (
    EmployeeInviteCreateSerializer,
    EmployeeInviteResponseSerializer,
    EmployeeInviteAcceptSerializer,
)
from user_accounts.services.employees import (
    invite_employee,
    accept_employee_invite,
    terminate_member,
)


def _is_platform_admin(user) -> bool:
    return bool(
        getattr(user, "is_platform_admin", False)
        or getattr(user, "is_superuser", False)
        or getattr(user, "is_staff", False)
    )


def _can_access_business(user, business: Business) -> bool:
    if _is_platform_admin(user):
        return True
    if getattr(business, "owner_id", None) == getattr(user, "id", None):
        return True
    return BusinessMember.objects.filter(
        business=business,
        user=user,
        is_active=True,
    ).exists()


def _can_manage_team(user, business: Business) -> bool:
    if _is_platform_admin(user):
        return True

    if getattr(business, "owner_id", None) == getattr(user, "id", None):
        return True

    member = BusinessMember.objects.filter(
        business=business,
        user=user,
        is_active=True,
    ).first()

    if not member:
        return False

    member_role = str(getattr(member, "role", "") or "").upper()
    return bool(
        getattr(member, "can_manage_team", False)
        or member_role in {"OWNER", "MANAGER", "DISPATCH", "ADMIN"}
    )


def _require_business_access(user, business: Business) -> None:
    if not _can_access_business(user, business):
        raise PermissionDenied("You do not have access to this business.")


def _require_team_manage_access(user, business: Business) -> None:
    if not _can_manage_team(user, business):
        raise PermissionDenied("You do not have permission to manage team members for this business.")


class BusinessViewSet(viewsets.ModelViewSet):
    serializer_class = BusinessSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user

        if _is_platform_admin(user):
            return Business.objects.all().order_by("-created_at")

        return (
            Business.objects.filter(
                Q(owner=user) | Q(members__user=user, members__is_active=True)
            )
            .distinct()
            .order_by("-created_at")
        )

    def perform_create(self, serializer):
        business = serializer.save(owner=self.request.user)

        membership, created = BusinessMember.objects.get_or_create(
            business=business,
            user=self.request.user,
            defaults={"role": BusinessMember.ROLE_OWNER, "is_active": True},
        )
        if created or membership.role != BusinessMember.ROLE_OWNER:
            membership.role = BusinessMember.ROLE_OWNER
            membership.is_active = True
            if hasattr(membership, "apply_role_defaults"):
                membership.apply_role_defaults()
            membership.save()

    @action(detail=False, methods=["get"], url_path="me")
    def me(self, request):
        qs = self.get_queryset()
        page = self.paginate_queryset(qs)
        if page is not None:
            ser = self.get_serializer(page, many=True)
            return self.get_paginated_response(ser.data)

        ser = self.get_serializer(qs, many=True)
        return Response(ser.data)


class BusinessTeamViewSet(viewsets.ViewSet):
    """
    Routes:
      POST /businesses/{id}/invite-employee/
      GET  /businesses/{id}/members/
    """

    permission_classes = [IsAuthenticated]

    def _get_business(self, pk: int) -> Business:
        try:
            return Business.objects.get(pk=pk)
        except Business.DoesNotExist:
            raise ValidationError({"detail": "Business not found."})

    @action(detail=True, methods=["get"], url_path="members")
    def members(self, request, pk=None):
        business = self._get_business(pk)
        _require_business_access(request.user, business)

        qs = (
            BusinessMember.objects.filter(business=business)
            .select_related("user")
            .order_by("id")
        )
        return Response(
            BusinessMemberSerializer(qs, many=True).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="invite-employee")
    def invite_employee(self, request, pk=None):
        business = self._get_business(pk)
        _require_team_manage_access(request.user, business)

        ser = EmployeeInviteCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        res = invite_employee(
            business=business,
            invited_by=request.user,
            email=ser.validated_data["email"],
            seat_role=ser.validated_data["role"],
            permissions=ser.validated_data.get("permissions") or None,
        )
        return Response(
            EmployeeInviteResponseSerializer(res.invite).data,
            status=status.HTTP_201_CREATED,
        )


class BusinessMemberViewSet(viewsets.ModelViewSet):
    """
    Routes:
      PATCH /business-members/{id}/
      POST  /business-members/{id}/terminate/
    """

    serializer_class = BusinessMemberSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user

        if _is_platform_admin(user):
            return BusinessMember.objects.select_related("user", "business").all().order_by("-created_at")

        business_ids = Business.objects.filter(
            Q(owner=user) | Q(members__user=user, members__is_active=True)
        ).values_list("id", flat=True)

        return (
            BusinessMember.objects.select_related("user", "business")
            .filter(business_id__in=business_ids)
            .order_by("-created_at")
        )

    def partial_update(self, request, *args, **kwargs):
        member = self.get_object()
        _require_team_manage_access(request.user, member.business)

        allowed = {
            "role",
            "is_active",
            "can_view_invoices",
            "can_send_quotes",
            "can_assign_tickets",
            "can_manage_team",
            "can_post_internal_messages",
            "can_manage_schedule",
            "can_close_tickets",
            "can_manage_invoices",
            "can_manage_settings",
            "can_view_financials",
            "can_create_tickets",
            "can_manage_categories",
            "can_manage_properties",
            "can_manage_connections",
        }
        payload = {k: v for k, v in request.data.items() if k in allowed}

        for k, v in payload.items():
            setattr(member, k, v)

        if payload.get("is_active") is False and getattr(member, "terminated_at", None) is None:
            terminate_member(member=member, terminated_by=request.user)

        member.save()
        return Response(self.get_serializer(member).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="terminate")
    def terminate(self, request, pk=None):
        member = self.get_object()
        _require_team_manage_access(request.user, member.business)

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