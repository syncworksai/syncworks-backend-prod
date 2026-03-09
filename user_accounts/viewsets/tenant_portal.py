from __future__ import annotations

from rest_framework import permissions, status, viewsets
from rest_framework.response import Response

from user_accounts.models import PMTenant, PMRentCharge


def _norm_email(s: str) -> str:
    return (s or "").strip().lower()


class TenantSummaryViewSet(viewsets.ViewSet):
    """
    Tenant portal summary (NO X-Business-Id required).

    IMPORTANT:
    Your PMTenant model currently has NO user FK (traceback confirms).
    So we resolve the tenant by matching tenant.email to request.user.email.
    """
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        user = request.user
        user_email = _norm_email(getattr(user, "email", ""))

        if not user_email:
            return Response(
                {"detail": "Your user account has no email; cannot resolve tenant profile."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        tenant = (
            PMTenant.objects
            .filter(email__iexact=user_email)
            .select_related("unit", "business", "property")
            .order_by("-id")
            .first()
        )

        if not tenant:
            return Response(
                {
                    "detail": "No tenant profile is linked to this account yet.",
                    "hint": "Invite flow should link tenant by email (PMTenant.email) and assign a unit.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        unit = getattr(tenant, "unit", None)

        # property might be on tenant.property or unit.property depending on schema
        prop = getattr(tenant, "property", None) or (getattr(unit, "property", None) if unit else None)

        return Response(
            {
                "tenant_id": tenant.id,
                "first_name": getattr(tenant, "first_name", "") or "",
                "last_name": getattr(tenant, "last_name", "") or "",
                "email": getattr(tenant, "email", "") or user_email,
                "phone": getattr(tenant, "phone", "") or "",
                "unit_id": getattr(unit, "id", None),
                "property_id": getattr(prop, "id", None),
                "business_id": getattr(tenant, "business_id", None),
                "status": getattr(tenant, "status", "") or "",
            }
        )


class TenantRentChargeViewSet(viewsets.ViewSet):
    """
    Tenant portal - rent charges list (NO X-Business-Id required).

    We resolve tenant by email then show PMRentCharge rows for that tenant.
    """
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        user = request.user
        user_email = _norm_email(getattr(user, "email", ""))

        if not user_email:
            return Response(
                {"detail": "Your user account has no email; cannot resolve tenant charges."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        tenant = PMTenant.objects.filter(email__iexact=user_email).order_by("-id").first()
        if not tenant:
            return Response(
                {"count": 0, "next": None, "previous": None, "results": []},
                status=status.HTTP_200_OK,
            )

        qs = PMRentCharge.objects.filter(tenant_id=tenant.id).order_by("-due_date", "-id")

        results = []
        for c in qs[:200]:
            results.append(
                {
                    "id": c.id,
                    "tenant_id": getattr(c, "tenant_id", None),
                    "unit_id": getattr(c, "unit_id", None),
                    "amount": str(getattr(c, "amount", "")),
                    "currency": getattr(c, "currency", "USD"),
                    "description": getattr(c, "description", "") or "",
                    "status": getattr(c, "status", "") or "",
                    "due_date": getattr(c, "due_date", None),
                    "created_at": getattr(c, "created_at", None),
                }
            )

        return Response(
            {"count": qs.count(), "next": None, "previous": None, "results": results},
            status=status.HTTP_200_OK,
        )
