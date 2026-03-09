# backend/user_accounts/viewsets/investor_portal.py
from __future__ import annotations

from django.db.models import Count, Q
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models.pm_property import PMProperty
from user_accounts.models.pm_property_ownership import PMPropertyOwnership
from user_accounts.models.pm_unit import PMUnit

# IMPORTANT: PMInvestor model path can differ across your build.
# If your PMInvestor lives in user_accounts.models (aggregated import), you can switch to:
# from user_accounts.models import PMInvestor
try:
    from user_accounts.models.pm_investor import PMInvestor  # type: ignore
except Exception:
    try:
        from user_accounts.models import PMInvestor  # type: ignore
    except Exception:
        PMInvestor = None  # type: ignore

from user_accounts.serializers.investor_portal import InvestorDashboardSerializer


def _is_platform_admin(user) -> bool:
    return bool(getattr(user, "is_superuser", False) or getattr(user, "is_platform_admin", False))


def _safe_decimal(x):
    try:
        return x if x is not None else None
    except Exception:
        return None


def _resolve_investor_or_none(request):
    """
    Returns PMInvestor instance or None.
    - For superusers: try to resolve if exists; if not, return None (but never block).
    - For normal users: resolve via pm_investor_profile OR PMInvestor(user=request.user).
    """
    user = request.user

    inv = getattr(user, "pm_investor_profile", None)
    if inv:
        return inv

    if PMInvestor is not None:
        # Common schema: PMInvestor has user FK
        try:
            inv2 = PMInvestor.objects.filter(user_id=user.id).order_by("-id").first()
            if inv2:
                return inv2
        except Exception:
            pass

    return None


class InvestorDashboardViewSet(viewsets.ViewSet):
    """
    Investor-side: returns a single dashboard payload.

    MUST NOT 403 for authenticated users because the frontend loads this
    on dashboards even when no investor exists yet.

    Route:
      /api/v1/investor/dashboard/
    """

    permission_classes = [IsAuthenticated]

    def list(self, request):
        user = request.user
        inv = _resolve_investor_or_none(request)

        # ✅ If no investor profile (or inactive), return SAFE empty payload (200)
        # Superuser should also never be blocked; they can still see an empty payload.
        if inv is None:
            payload = {
                "investor_id": None,
                "investor_name": getattr(user, "email", "") or str(user),
                "businesses": [],
                "properties": [],
                "needs_claim": True,
                "message": "Investor profile not linked. Claim your investor profile to see investor dashboards.",
            }
            ser = InvestorDashboardSerializer(data=payload)
            ser.is_valid(raise_exception=True)
            return Response(ser.data)

        inv_status = (getattr(inv, "status", "") or "").upper()
        if inv_status and inv_status != "ACTIVE" and not _is_platform_admin(user):
            payload = {
                "investor_id": getattr(inv, "id", None),
                "investor_name": getattr(inv, "full_name", "") or getattr(inv, "email", "") or getattr(user, "email", "") or str(user),
                "businesses": [],
                "properties": [],
                "needs_claim": False,
                "message": "Investor profile is inactive.",
            }
            ser = InvestorDashboardSerializer(data=payload)
            ser.is_valid(raise_exception=True)
            return Response(ser.data)

        # Only ACCEPTED connections if present (safe if model doesn't have it)
        business_ids = []
        try:
            business_ids = list(inv.connections.filter(status="ACCEPTED").values_list("business_id", flat=True))
        except Exception:
            business_ids = []

        # Owned properties (via ownership model)
        owned_ids = list(PMPropertyOwnership.objects.filter(investor=inv).values_list("property_id", flat=True))
        props = PMProperty.objects.filter(id__in=owned_ids)
        units = PMUnit.objects.filter(property_id__in=owned_ids)

        occupied_counts = (
            units.values("property_id")
            .annotate(
                unit_count=Count("id"),
                occupied_count=Count("id", filter=Q(status=PMUnit.Status.OCCUPIED)),
            )
        )
        occ_map = {row["property_id"]: row for row in occupied_counts}

        rows = []
        for p in props:
            u_primary = (
                units.filter(property_id=p.id, status=PMUnit.Status.OCCUPIED).order_by("id").first()
                or units.filter(property_id=p.id).order_by("id").first()
            )

            rent_amount = None
            balance_due = None
            days_past_due = None
            rent_status = "UNKNOWN"

            if u_primary is not None:
                rent_amount = getattr(u_primary, "rent_amount", None)
                if rent_amount is None:
                    rent_amount = getattr(u_primary, "market_rent", None)

                balance_due = getattr(u_primary, "balance_due", None)
                days_past_due = getattr(u_primary, "days_past_due", None)

                if balance_due is not None:
                    try:
                        rent_status = "PAST_DUE" if float(balance_due) > 0 else "CURRENT"
                    except Exception:
                        rent_status = "UNKNOWN"

            open_workorders = 0
            recent_workorders_30d = 0

            occ = occ_map.get(p.id, {"unit_count": 0, "occupied_count": 0})

            rows.append(
                {
                    "property_id": p.id,
                    "property_name": getattr(p, "name", "") or "Property",
                    "address": getattr(p, "address", "") or "",
                    "city": getattr(p, "city", "") or "",
                    "state": getattr(p, "state", "") or "",
                    "zip": getattr(p, "zip", "") or "",
                    "unit_count": int(occ.get("unit_count") or 0),
                    "occupied_count": int(occ.get("occupied_count") or 0),
                    "rent_amount": _safe_decimal(rent_amount),
                    "balance_due": _safe_decimal(balance_due),
                    "days_past_due": days_past_due if days_past_due is not None else None,
                    "rent_status": rent_status,
                    "open_workorders": open_workorders,
                    "recent_workorders_30d": recent_workorders_30d,
                }
            )

        payload = {
            "investor_id": getattr(inv, "id", None),
            "investor_name": getattr(inv, "full_name", "") or getattr(inv, "email", "") or getattr(user, "email", "") or str(user),
            "businesses": business_ids,
            "properties": rows,
            "needs_claim": False,
            "message": "",
        }

        ser = InvestorDashboardSerializer(data=payload)
        ser.is_valid(raise_exception=True)
        return Response(ser.data)