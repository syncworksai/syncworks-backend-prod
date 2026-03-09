# backend/user_accounts/viewsets/pm_workorders.py
from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models import Business, PMEmployee, PMWorkOrder, Ticket
from user_accounts.permissions import IsBusinessMember
from user_accounts.serializers.pm_workorders import (
    PMWorkOrderAssignSerializer,
    PMWorkOrderSerializer,
)


def _get_business_id_from_request(request) -> int | None:
    bid = request.headers.get("X-Business-Id") or request.META.get("HTTP_X_BUSINESS_ID")
    if not bid:
        bid = request.query_params.get("business_id") or request.query_params.get("business")
    try:
        return int(bid) if bid else None
    except Exception:
        return None


class PMWorkOrderViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """
    /api/v1/pm/workorders/
    Requires: Authorization + X-Business-Id
    """

    serializer_class = PMWorkOrderSerializer
    permission_classes = [IsAuthenticated, IsBusinessMember]

    def get_queryset(self):
        biz_id = _get_business_id_from_request(self.request)
        qs = PMWorkOrder.objects.all()
        if not biz_id:
            return qs.none()

        return (
            qs.filter(business_id=biz_id)
            .select_related(
                "business",
                "property",
                "unit",
                "tenant",
                "created_by",
                "assigned_member",       # User FK
                "marketplace_ticket",
            )
        )

    def perform_create(self, serializer):
        biz_id = _get_business_id_from_request(self.request)
        if not biz_id:
            raise ValidationError({"detail": "X-Business-Id header is required."})

        business = Business.objects.filter(id=biz_id, is_active=True).first()
        if not business:
            raise ValidationError({"detail": "Business not found or inactive."})

        serializer.save(business=business, created_by=self.request.user)

    def perform_update(self, serializer):
        updated: PMWorkOrder = serializer.save()
        if updated.status == PMWorkOrder.Status.COMPLETED and not updated.completed_at:
            updated.completed_at = timezone.now()
            updated.save(update_fields=["completed_at"])

    def _resolve_assignment_target(self, biz_id: int, assigned_member_id: int):
        """
        Accepts assigned_member_id as:
          - BusinessMember.id (recommended)
          - BusinessMember.user_id (fallback)
          - PMEmployee.id (fallback; assigns email only)
        Returns:
          dict:
            {
              "user": User | None,
              "email": str,
              "source": "business_member" | "pm_employee",
              "bm_id": int | None,
              "employee_id": int | None,
            }
        """
        # Local import to avoid circular import risk
        from user_accounts.models import BusinessMember

        # 1) BusinessMember.id
        bm = BusinessMember.objects.filter(id=assigned_member_id, business_id=biz_id, is_active=True).select_related("user").first()
        if bm and bm.user:
            email = (bm.user.email or "").strip()
            if not email:
                raise ValidationError({"detail": "Assigned user has no email."})
            return {"user": bm.user, "email": email, "source": "business_member", "bm_id": bm.id, "employee_id": None}

        # 2) BusinessMember.user_id
        bm = BusinessMember.objects.filter(business_id=biz_id, user_id=assigned_member_id, is_active=True).select_related("user").first()
        if bm and bm.user:
            email = (bm.user.email or "").strip()
            if not email:
                raise ValidationError({"detail": "Assigned user has no email."})
            return {"user": bm.user, "email": email, "source": "business_member", "bm_id": bm.id, "employee_id": None}

        # 3) PMEmployee.id (email-only assignment)
        emp = PMEmployee.objects.filter(id=assigned_member_id, business_id=biz_id, is_active=True).first()
        if emp:
            email = (emp.email or "").strip()
            if not email:
                raise ValidationError({"detail": "PMEmployee has no email."})
            # If PMEmployee has a linked user_id, we can attach it
            user = None
            if emp.user_id:
                # Safe import: AUTH_USER_MODEL is your User model
                from django.contrib.auth import get_user_model
                User = get_user_model()
                user = User.objects.filter(id=emp.user_id, is_active=True).first()
            return {"user": user, "email": email, "source": "pm_employee", "bm_id": None, "employee_id": emp.id}

        raise ValidationError({"detail": "assigned_member_id is not a valid active BusinessMember or PMEmployee for this business."})

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        """
        POST /api/v1/pm/workorders/{id}/assign/

        Body:
          { "mode": "TECH", "assigned_member_id": 6 }         # BusinessMember.id (recommended)
          OR { "mode": "TECH", "assigned_member_id": 11 }     # BusinessMember.user_id (accepted)
          OR { "mode": "TECH", "assigned_member_id": 2 }      # PMEmployee.id (accepted)
          OR { "mode": "MARKETPLACE" }
          OR { "mode": "CLEAR" }
        """
        biz_id = _get_business_id_from_request(request)
        if not biz_id:
            raise ValidationError({"detail": "X-Business-Id header is required."})

        wo: PMWorkOrder = self.get_object()  # filtered by business in get_queryset

        s = PMWorkOrderAssignSerializer(data=request.data or {})
        s.is_valid(raise_exception=True)
        mode = s.validated_data["mode"]

        business = Business.objects.filter(id=biz_id, is_active=True).first()
        if not business:
            raise ValidationError({"detail": "Business not found or inactive."})

        with transaction.atomic():
            if mode == "CLEAR":
                wo.assignment_mode = PMWorkOrder.AssignmentMode.NONE
                wo.assigned_member = None
                wo.assigned_to_email = ""
                wo.save(update_fields=["assignment_mode", "assigned_member", "assigned_to_email", "updated_at"])
                return Response(PMWorkOrderSerializer(wo).data)

            if mode == "TECH":
                assigned_member_id = s.validated_data.get("assigned_member_id")
                if not assigned_member_id:
                    raise ValidationError({"detail": "assigned_member_id is required when mode=TECH."})

                target = self._resolve_assignment_target(biz_id=biz_id, assigned_member_id=int(assigned_member_id))

                wo.assignment_mode = PMWorkOrder.AssignmentMode.TECH
                wo.assigned_to_email = target["email"]

                # Only set FK if we resolved a real User
                wo.assigned_member = target["user"]

                # optional: auto move status
                if wo.status == PMWorkOrder.Status.OPEN:
                    wo.status = PMWorkOrder.Status.IN_PROGRESS

                wo.save(update_fields=["assignment_mode", "assigned_member", "assigned_to_email", "status", "updated_at"])
                return Response(PMWorkOrderSerializer(wo).data)

            if mode == "MARKETPLACE":
                # Already sent
                if wo.marketplace_ticket_id:
                    wo.assignment_mode = PMWorkOrder.AssignmentMode.MARKETPLACE
                    wo.marketplace_requested_at = wo.marketplace_requested_at or timezone.now()
                    wo.save(update_fields=["assignment_mode", "marketplace_requested_at", "updated_at"])
                    return Response(PMWorkOrderSerializer(wo).data)

                customer = request.user

                # payer is the PM business (not tenant)
                t = Ticket.objects.create(
                    customer=customer,
                    is_marketplace=True,
                    status=Ticket.Status.NEW,
                    payer_business=business,
                )

                wo.assignment_mode = PMWorkOrder.AssignmentMode.MARKETPLACE
                wo.marketplace_ticket = t
                wo.marketplace_requested_at = timezone.now()
                wo.save(update_fields=["assignment_mode", "marketplace_ticket", "marketplace_requested_at", "updated_at"])

                return Response(PMWorkOrderSerializer(wo).data)

        raise ValidationError({"detail": "Invalid mode"})
