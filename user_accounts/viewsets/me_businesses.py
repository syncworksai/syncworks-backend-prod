from __future__ import annotations

from django.conf import settings
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models import Business, BusinessMember
from user_accounts.models.promo import PromoCode, PromoRedemption
from user_accounts.models.user_billing import UserBillingProfile
from user_accounts.serializers.business import BusinessSerializer


def _legacy_promo_code() -> str:
    return str(getattr(settings, "SW_PROMO_UPGRADE_CODE", "SWFF26") or "SWFF26").strip()


def _apply_user_private_access_to_business(user, business: Business) -> None:
    """
    If the user previously unlocked SBO/private access BEFORE creating a business,
    inherit that waiver onto the new business here.
    """
    prof = UserBillingProfile.objects.filter(user=user).first()
    if not prof or not getattr(prof, "beta_access_granted", False):
        return

    changed = []

    if getattr(prof, "beta_billing_exempt", False) and not getattr(business, "billing_exempt", False):
        business.billing_exempt = True
        business.billing_exempt_reason = "Private access code"
        business.billing_exempt_until = None
        changed.extend(["billing_exempt", "billing_exempt_reason", "billing_exempt_until"])

    if getattr(prof, "beta_subscriptions_waived", False) and not getattr(business, "subscriptions_exempt", False):
        business.subscriptions_exempt = True
        business.subscriptions_exempt_reason = "Private access code"
        business.subscriptions_exempt_until = None
        changed.extend(["subscriptions_exempt", "subscriptions_exempt_reason", "subscriptions_exempt_until"])

    if changed:
        business.save(update_fields=changed)

    code = str(getattr(prof, "beta_access_code", "") or "").strip()
    if not code:
        return

    promo = PromoCode.objects.filter(code__iexact=code).first()
    if promo:
        already = PromoRedemption.objects.filter(promo=promo, business=business).exists()
        if not already:
            PromoRedemption.objects.create(promo=promo, user=user, business=business)
            promo.redemption_count = (promo.redemption_count or 0) + 1
            promo.save(update_fields=["redemption_count"])
    elif code == _legacy_promo_code():
        # legacy code path intentionally has no PromoCode row to attach
        pass


class MeBusinessesViewSet(viewsets.ViewSet):
    """
    GET /api/v1/me/businesses/
    Returns businesses the current user belongs to (via BusinessMember).

    POST /api/v1/me/businesses/create/
    Creates a new Business owned by the current user and an OWNER BusinessMember.
    Does NOT require existing X-Business-Id context.
    """

    permission_classes = [IsAuthenticated]

    def _format_membership(self, request, m: BusinessMember) -> dict:
        b = getattr(m, "business", None)
        if not b:
            return {}

        business_data = BusinessSerializer(b, context={"request": request}).data

        return {
            "business_id": b.id,
            "business_name": getattr(b, "name", f"Business {b.id}"),
            "role": getattr(m, "role", "") or "",
            "is_owner": bool(getattr(m, "is_owner", False)),
            "can_assign_tickets": bool(getattr(m, "can_assign_tickets", False)),
            "can_close_tickets": bool(getattr(m, "can_close_tickets", False)),
            "can_manage_billing": bool(getattr(m, "can_manage_billing", False)),
            "can_manage_team": bool(getattr(m, "can_manage_team", False)),
            "business": business_data,
        }

    def list(self, request):
        user = request.user

        memberships = (
            BusinessMember.objects.filter(user=user, is_active=True)
            .select_related("business")
            .order_by("-created_at")
        )

        out: list[dict] = []
        for m in memberships:
            row = self._format_membership(request, m)
            if row:
                out.append(row)

        return Response(out)

    @action(detail=False, methods=["post"], url_path="create")
    def create_business(self, request):
        user = request.user
        data = request.data or {}

        name = (data.get("name") or "").strip()
        if not name:
            return Response({"detail": "name is required"}, status=status.HTTP_400_BAD_REQUEST)

        b = Business.objects.create(
            owner=user,
            name=name,
            business_email=(data.get("business_email") or "").strip(),
            owner_name=(data.get("owner_name") or "").strip(),
            phone=(data.get("phone") or "").strip(),
            base_zip=(data.get("base_zip") or "").strip(),
            service_radius_miles=int(data.get("service_radius_miles") or 25),
            accepts_marketplace_tickets=bool(data.get("accepts_marketplace_tickets", True)),
        )

        services = data.get("services_offered")
        if isinstance(services, list) and services:
            try:
                b.services_offered.set([int(x) for x in services if str(x).strip().isdigit()])
            except Exception:
                pass

        # ✅ Apply user-level private access to the newly-created business
        _apply_user_private_access_to_business(user, b)

        m, created = BusinessMember.objects.get_or_create(
            business=b,
            user=user,
            defaults={"role": BusinessMember.ROLE_OWNER, "is_active": True},
        )

        m.role = BusinessMember.ROLE_OWNER
        m.is_active = True
        if hasattr(m, "apply_role_defaults"):
            m.apply_role_defaults()
        m.save()

        if getattr(user, "role", "CUSTOMER") != "SBO":
            user.role = "SBO"
            user.save(update_fields=["role"])

        m = BusinessMember.objects.filter(id=m.id).select_related("business").first()

        payload = self._format_membership(request, m) if m else {}
        if not payload:
            return Response({"detail": "Failed to create business membership"}, status=500)

        return Response(payload, status=status.HTTP_201_CREATED)