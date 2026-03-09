# backend/user_accounts/viewsets/pm_employees.py
from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models import Business, BusinessMember
from user_accounts.models.pm_employees import PMEmployee, PMEmployeeInvite
from user_accounts.serializers.pm_employees import (
    PMEmployeeInviteAcceptSerializer,
    PMEmployeeInviteCreateSerializer,
    PMEmployeeInviteSerializer,
    PMEmployeeSerializer,
)

FREE_PM_EMPLOYEE_SEATS = 3


def _get_business_from_header(request) -> Business:
    bid = request.headers.get("X-Business-Id") or request.META.get("HTTP_X_BUSINESS_ID")
    if not bid:
        raise ValidationError({"detail": "X-Business-Id header is required."})
    try:
        bid_int = int(str(bid))
    except Exception:
        raise ValidationError({"detail": "Invalid X-Business-Id header."})

    try:
        return Business.objects.get(id=bid_int)
    except Business.DoesNotExist:
        raise ValidationError({"detail": "Business not found."})


def _ensure_business_access(request, business: Business):
    if request.user.is_superuser:
        return
    ok = BusinessMember.objects.filter(business=business, user=request.user, is_active=True).exists()
    if not ok:
        raise PermissionDenied("You do not have access to this business.")


def _ensure_can_manage_employees(request, business: Business):
    """
    Who can manage PM employees:
    - superuser always
    - any active BusinessMember for now
    (Later: map BusinessMember roles/flags to true HR permissions)
    """
    if request.user.is_superuser:
        return
    ok = BusinessMember.objects.filter(business=business, user=request.user, is_active=True).exists()
    if not ok:
        raise PermissionDenied("Not allowed.")


def _enforce_seat_limit(business: Business, bypass: bool):
    if bypass:
        return
    active_count = PMEmployee.objects.filter(business=business, is_active=True).count()
    if active_count >= FREE_PM_EMPLOYEE_SEATS:
        raise ValidationError(
            {"detail": f"Free plan includes {FREE_PM_EMPLOYEE_SEATS} employee seats. Upgrade to add more."}
        )


class PMEmployeeViewSet(viewsets.ModelViewSet):
    """
    CRUD for PMEmployee records.
    NOTE: Invites are NOT mounted under this router because /pm/employees/<pk>/ would swallow 'invites'.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = PMEmployeeSerializer

    def get_queryset(self):
        business = _get_business_from_header(self.request)
        _ensure_business_access(self.request, business)
        return PMEmployee.objects.filter(business=business).order_by("-created_at")

    def perform_create(self, serializer):
        business = _get_business_from_header(self.request)
        _ensure_can_manage_employees(self.request, business)
        _enforce_seat_limit(business, bypass=bool(self.request.user.is_superuser))
        serializer.save(business=business)

    @action(detail=False, methods=["get"], url_path="seats")
    def seats(self, request):
        business = _get_business_from_header(request)
        _ensure_business_access(request, business)

        active_count = PMEmployee.objects.filter(business=business, is_active=True).count()
        return Response(
            {
                "business_id": business.id,
                "free_seats": FREE_PM_EMPLOYEE_SEATS,
                "active_employees": active_count,
                "can_add_more": bool(request.user.is_superuser or active_count < FREE_PM_EMPLOYEE_SEATS),
            }
        )


class PMEmployeeInviteViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """
    Invite list/create.
    IMPORTANT: This must be mounted via explicit `path()` routes (NOT router.register under /pm/employees/*)
    or it will be interpreted as /pm/employees/<pk>/ with pk='invites'.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = PMEmployeeInviteSerializer

    def get_queryset(self):
        business = _get_business_from_header(self.request)
        _ensure_business_access(self.request, business)
        return PMEmployeeInvite.objects.filter(business=business).order_by("-created_at")

    def create(self, request, *args, **kwargs):
        business = _get_business_from_header(request)
        _ensure_can_manage_employees(request, business)

        data_ser = PMEmployeeInviteCreateSerializer(data=request.data)
        data_ser.is_valid(raise_exception=True)

        email = data_ser.validated_data["email"].strip().lower()
        employee_id = data_ser.validated_data.get("employee_id")

        employee = None
        if employee_id:
            employee = PMEmployee.objects.filter(business=business, id=employee_id).first()
            if not employee:
                raise ValidationError({"detail": "Employee not found for this business."})
        else:
            # If no employee_id, optionally create/update a placeholder employee record for this email
            employee = PMEmployee.objects.filter(business=business, email=email).first()
            if not employee:
                _enforce_seat_limit(business, bypass=bool(request.user.is_superuser))
                employee = PMEmployee.objects.create(
                    business=business,
                    email=email,
                    full_name=data_ser.validated_data.get("full_name", "") or "",
                    job_title=data_ser.validated_data.get("job_title", "") or "",
                    role=data_ser.validated_data.get("role", "VIEW_ONLY") or "VIEW_ONLY",
                    is_active=True,
                    can_view_financials=bool(data_ser.validated_data.get("can_view_financials", False)),
                    can_manage_financials=bool(data_ser.validated_data.get("can_manage_financials", False)),
                    can_manage_properties=bool(data_ser.validated_data.get("can_manage_properties", False)),
                    can_manage_tenants=bool(data_ser.validated_data.get("can_manage_tenants", False)),
                    can_manage_documents=bool(data_ser.validated_data.get("can_manage_documents", False)),
                    can_manage_work_orders=bool(data_ser.validated_data.get("can_manage_work_orders", False)),
                    can_manage_employees=bool(data_ser.validated_data.get("can_manage_employees", False)),
                )
            else:
                # If employee exists, allow updating role/title/permissions via invite create (optional)
                for field in [
                    "full_name",
                    "job_title",
                    "role",
                    "can_view_financials",
                    "can_manage_financials",
                    "can_manage_properties",
                    "can_manage_tenants",
                    "can_manage_documents",
                    "can_manage_work_orders",
                    "can_manage_employees",
                ]:
                    if field in data_ser.validated_data:
                        setattr(employee, field, data_ser.validated_data[field])
                employee.save()

        inv = PMEmployeeInvite.objects.create(
            business=business,
            employee=employee,
            email=email,
            created_by=request.user,
        )

        return Response(PMEmployeeInviteSerializer(inv).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="accept")
    @transaction.atomic
    def accept(self, request):
        """
        Employee accepts invite code while logged in.
        Links invite to a PMEmployee and sets employee.user=request.user.
        """
        ser = PMEmployeeInviteAcceptSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        code = ser.validated_data["code"].strip()
        invite = PMEmployeeInvite.objects.select_for_update().filter(code=code).first()
        if not invite:
            raise ValidationError({"detail": "Invalid invite code."})

        if invite.revoked_at:
            raise ValidationError({"detail": "Invite was revoked."})
        if invite.accepted_at:
            raise ValidationError({"detail": "Invite already accepted."})
        if invite.expires_at and timezone.now() > invite.expires_at:
            raise ValidationError({"detail": "Invite expired."})

        business = invite.business

        # Seat enforcement at acceptance time too
        _enforce_seat_limit(business, bypass=bool(request.user.is_superuser))

        employee = invite.employee
        if not employee:
            employee = PMEmployee.objects.filter(business=business, email=invite.email).first()
        if not employee:
            employee = PMEmployee.objects.create(
                business=business,
                email=invite.email,
                full_name="",
                job_title="",
                role="VIEW_ONLY",
                is_active=True,
            )

        # Single sign-on link
        employee.user = request.user
        employee.email = employee.email or invite.email
        employee.is_active = True
        employee.save()

        invite.accepted_at = timezone.now()
        invite.save(update_fields=["accepted_at"])

        return Response(
            {
                "detail": "Invite accepted.",
                "employee": PMEmployeeSerializer(employee).data,
            },
            status=status.HTTP_200_OK,
        )
