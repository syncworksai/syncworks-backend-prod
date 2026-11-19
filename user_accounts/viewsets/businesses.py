# backend/user_accounts/viewsets/businesses.py
from __future__ import annotations

import os

from django.conf import settings
from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models import Business, BusinessMember
from user_accounts.serializers.business import BusinessSerializer, BusinessMemberSerializer
from user_accounts.serializers.employees import (
    EmployeeInviteAcceptSerializer,
    EmployeeInviteCreateSerializer,
    EmployeeInviteResponseSerializer,
)
from user_accounts.services.employees import (
    accept_employee_invite,
    invite_employee,
    terminate_member,
)


MAX_LOGO_UPLOAD_MB = 5
ALLOWED_LOGO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".svg"}


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


def _can_manage_business(user, business: Business) -> bool:
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
        getattr(member, "can_manage_settings", False)
        or member_role in {"OWNER", "MANAGER", "ADMIN"}
    )


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

    # Delegation is explicit: dispatcher and manager titles alone must not
    # confer the authority to edit employee permissions.
    return bool(getattr(member, "can_manage_team", False))


def _require_business_access(user, business: Business) -> None:
    if not _can_access_business(user, business):
        raise PermissionDenied("You do not have access to this business.")


def _require_business_manage_access(user, business: Business) -> None:
    if not _can_manage_business(user, business):
        raise PermissionDenied("You do not have permission to manage this business.")


def _require_team_manage_access(user, business: Business) -> None:
    if not _can_manage_team(user, business):
        raise PermissionDenied(
            "You do not have permission to manage team members for this business."
        )


def _owner_role_value() -> str:
    if hasattr(BusinessMember, "ROLE_OWNER"):
        return BusinessMember.ROLE_OWNER

    member_role = getattr(BusinessMember, "MemberRole", None)
    if member_role and hasattr(member_role, "OWNER"):
        return member_role.OWNER

    return "OWNER"


def _logo_url(request, business: Business) -> str | None:
    try:
        logo = getattr(business, "logo", None)
        if not logo:
            return None
        if request:
            return request.build_absolute_uri(logo.url)
        return logo.url
    except Exception:
        return None


def _validate_logo_file(file_obj) -> None:
    if not file_obj:
        raise ValidationError({"logo": ["No logo file was uploaded."]})

    size = int(getattr(file_obj, "size", 0) or 0)
    max_bytes = MAX_LOGO_UPLOAD_MB * 1024 * 1024

    if size > max_bytes:
        raise ValidationError(
            {"logo": [f"Logo must be {MAX_LOGO_UPLOAD_MB}MB or smaller."]}
        )

    filename = str(getattr(file_obj, "name", "") or "").strip()
    _, ext = os.path.splitext(filename.lower())

    if ext not in ALLOWED_LOGO_EXTENSIONS:
        raise ValidationError(
            {"logo": ["Logo must be a PNG, JPG, JPEG, WEBP, or SVG file."]}
        )


class BusinessViewSet(viewsets.ModelViewSet):
    """
    /businesses/
    /businesses/{id}/
    /businesses/me/
    /businesses/{id}/upload-logo/

    Supports:
    - JSON PATCH for normal settings
    - multipart upload through dedicated upload-logo endpoint
    """

    serializer_class = BusinessSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get_queryset(self):
        user = self.request.user
        base_qs = Business.objects.prefetch_related("services_offered")

        if _is_platform_admin(user):
            return base_qs.all().order_by("-created_at")

        return (
            base_qs.filter(
                Q(owner=user) | Q(members__user=user, members__is_active=True)
            )
            .distinct()
            .order_by("-created_at")
        )

    def perform_create(self, serializer):
        business = serializer.save(owner=self.request.user)
        owner_role = _owner_role_value()

        membership, created = BusinessMember.objects.get_or_create(
            business=business,
            user=self.request.user,
            defaults={"role": owner_role, "is_active": True},
        )

        if created or str(getattr(membership, "role", "")) != str(owner_role):
            membership.role = owner_role
            membership.is_active = True

            if hasattr(membership, "apply_role_defaults"):
                membership.apply_role_defaults()

            membership.save()

    def perform_update(self, serializer):
        business = self.get_object()
        _require_business_manage_access(self.request.user, business)
        serializer.save()

    def retrieve(self, request, *args, **kwargs):
        business = self.get_object()
        _require_business_access(request.user, business)
        return super().retrieve(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return super().partial_update(request, *args, **kwargs)

    @action(
        detail=True,
        methods=["post"],
        url_path="upload-logo",
        parser_classes=[MultiPartParser, FormParser],
    )
    def upload_logo(self, request, pk=None):
        business = self.get_object()
        _require_business_manage_access(request.user, business)

        file_obj = request.FILES.get("logo") or request.FILES.get("file")
        _validate_logo_file(file_obj)

        try:
            os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
        except Exception:
            # Let the actual save expose the real error if directory creation fails.
            pass

        try:
            business.logo = file_obj
            business.save(update_fields=["logo"])
        except Exception as exc:
            return Response(
                {
                    "detail": "Logo upload failed while saving the file.",
                    "error": str(exc),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "id": business.id,
                "name": business.name,
                "logo_url": _logo_url(request, business),
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], url_path="access-contexts")
    def access_contexts(self, request):
        """Server-authoritative contexts: one account can own and staff businesses."""
        qs = self.get_queryset().select_related("owner")
        memberships = {
            member.business_id: member
            for member in BusinessMember.objects.filter(
                user=request.user, business__in=qs, is_active=True
            )
        }
        contexts = []
        for business in qs:
            owner = business.owner_id == request.user.id
            member = memberships.get(business.id)
            permissions = {
                field: bool(owner or (member and getattr(member, field, False)))
                for field in (
                    "can_manage_team", "can_manage_settings", "can_view_financials",
                    "can_manage_invoices", "can_create_tickets", "can_assign_tickets",
                    "can_close_tickets", "can_manage_schedule", "can_manage_categories",
                    "can_manage_properties", "can_manage_connections",
                )
            }
            contexts.append({
                "business_id": business.id,
                "business_name": business.name,
                "is_owner": owner,
                "can_access_ceo": owner,
                "role": "OWNER" if owner else (member.role if member else None),
                "permissions": permissions,
            })
        return Response({"businesses": contexts}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="me")
    def me(self, request):
        qs = self.get_queryset()
        page = self.paginate_queryset(qs)

        if page is not None:
            ser = self.get_serializer(page, many=True)
            return self.get_paginated_response(ser.data)

        ser = self.get_serializer(qs, many=True)
        return Response(ser.data, status=status.HTTP_200_OK)


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
            **request.data,
        )

        return Response(
            EmployeeInviteResponseSerializer(res.invite).data,
            status=status.HTTP_201_CREATED,
        )


class BusinessMemberViewSet(viewsets.ModelViewSet):
    """Business-scoped employee access; owner role is never delegated here."""

    serializer_class = BusinessMemberSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "head", "options", "patch", "post"]

    def get_queryset(self):
        user = self.request.user
        qs = BusinessMember.objects.select_related("user", "business")
        if _is_platform_admin(user):
            return qs.order_by("-created_at")
        managed_business_ids = Business.objects.filter(owner=user).values_list("id", flat=True)
        delegated_business_ids = BusinessMember.objects.filter(
            user=user, is_active=True, can_manage_team=True
        ).values_list("business_id", flat=True)
        return qs.filter(
            Q(user=user) | Q(business_id__in=managed_business_ids)
            | Q(business_id__in=delegated_business_ids)
        ).distinct().order_by("-created_at")

    @action(detail=False, methods=["get"], url_path="me")
    def me(self, request):
        """Only the caller's memberships. An owner needs no employee seat."""
        qs = BusinessMember.objects.filter(user=request.user, is_active=True).select_related("user", "business")
        return Response(self.get_serializer(qs, many=True).data)

    def partial_update(self, request, *args, **kwargs):
        member = self.get_object()
        _require_team_manage_access(request.user, member.business)
        actor_is_owner = member.business.owner_id == request.user.id
        is_admin = _is_platform_admin(request.user)
        privileged = actor_is_owner or is_admin

        if member.user_id == member.business.owner_id or str(member.role).upper() == "OWNER":
            raise PermissionDenied("Business ownership cannot be changed through employee management.")
        if member.user_id == request.user.id:
            raise PermissionDenied("You cannot change your own employee permissions.")

        permission_keys = {
            "can_manage_team", "can_manage_settings", "can_view_financials",
            "can_manage_invoices", "can_create_tickets", "can_assign_tickets",
            "can_close_tickets", "can_manage_schedule", "can_manage_categories",
            "can_manage_properties", "can_manage_connections",
        }
        payload = {k: v for k, v in request.data.items() if k in permission_keys | {"role", "is_active"}}
        requested_role = str(payload.get("role", member.role)).upper()
        if requested_role in {"OWNER", "ADMIN", "CEO"}:
            raise PermissionDenied("Owner and platform roles cannot be assigned to employees.")
        allowed_roles = {"TECHNICIAN", "TECH", "DISPATCH", "ACCOUNTING", "MANAGER", "HR"}
        if requested_role not in allowed_roles:
            raise ValidationError({"role": "Unknown business role."})
        if not privileged:
            if "role" in payload and requested_role not in {"TECHNICIAN", "TECH", "DISPATCH", "ACCOUNTING", "HR"}:
                raise PermissionDenied("HR cannot assign management or executive roles.")
            for key in ("can_manage_team", "can_manage_settings", "can_view_financials", "can_manage_invoices", "can_manage_connections", "can_manage_properties"):
                if payload.get(key) is True and not getattr(member, key, False):
                    raise PermissionDenied(f"Only the owner may grant {key}.")
        serializer = self.get_serializer(member, data=payload, partial=True)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        if payload.get("is_active") is False and instance.is_active is False:
            # Preserve existing termination side effects.
            terminate_member(member=instance, terminated_by=request.user)
        return Response(self.get_serializer(instance).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="terminate")
    def terminate(self, request, pk=None):
        member = self.get_object()
        _require_team_manage_access(request.user, member.business)
        if member.user_id in {request.user.id, member.business.owner_id} or str(member.role).upper() == "OWNER":
            raise PermissionDenied("Cannot terminate your own or the business owner's access.")
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