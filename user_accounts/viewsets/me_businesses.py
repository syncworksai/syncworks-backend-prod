# backend/user_accounts/viewsets/me_businesses.py
from __future__ import annotations

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models import Business, BusinessMember
from user_accounts.serializers.business import BusinessSerializer


class MeBusinessesViewSet(viewsets.ViewSet):
    """
    GET /api/v1/me/businesses/
    Returns businesses the current user belongs to (via BusinessMember).

    Response includes BOTH:
      - flattened business fields for easy UI use (business_id, business_name)
      - the full BusinessSerializer payload (business)
      - membership metadata (role, is_owner, permission flags)

    POST /api/v1/me/businesses/create/
    Creates a new Business owned by the current user and an OWNER BusinessMember.
    This endpoint does NOT require existing X-Business-Id context (used for first-time onboarding).
    """

    permission_classes = [IsAuthenticated]

    def _format_membership(self, request, m: BusinessMember) -> dict:
        b = getattr(m, "business", None)
        if not b:
            return {}

        business_data = BusinessSerializer(b, context={"request": request}).data

        return {
            # flattened (easy for dropdowns)
            "business_id": b.id,
            "business_name": getattr(b, "name", f"Business {b.id}"),

            # membership metadata
            "role": getattr(m, "role", "") or "",
            "is_owner": bool(getattr(m, "is_owner", False)),

            # common permission flags used elsewhere in your codebase
            "can_assign_tickets": bool(getattr(m, "can_assign_tickets", False)),
            "can_close_tickets": bool(getattr(m, "can_close_tickets", False)),
            "can_manage_billing": bool(getattr(m, "can_manage_billing", False)),
            "can_manage_team": bool(getattr(m, "can_manage_team", False)),

            # full business payload (for future dashboards)
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
        """
        Create a new business + owner membership for the current user.
        Does NOT require X-Business-Id (this is used to bootstrap first business).
        """
        user = request.user
        data = request.data or {}

        name = (data.get("name") or "").strip()
        if not name:
            return Response({"detail": "name is required"}, status=status.HTTP_400_BAD_REQUEST)

        # Create business
        b = Business.objects.create(
            owner=user,
            name=name,
            business_email=(data.get("business_email") or "").strip(),
            owner_name=(data.get("owner_name") or "").strip(),
            phone=(data.get("phone") or "").strip(),
            base_zip=(data.get("base_zip") or "").strip(),
            service_radius_miles=int(data.get("service_radius_miles") or 25),
            accepts_marketplace_tickets=bool(
                data.get("accepts_marketplace_tickets", True)
            ),
        )

        # Apply services_offered if provided (list of ids)
        services = data.get("services_offered")
        if isinstance(services, list) and services:
            try:
                b.services_offered.set([int(x) for x in services if str(x).strip().isdigit()])
            except Exception:
                # keep creation successful even if bad payload
                pass

        # Create owner membership with role defaults
        m, created = BusinessMember.objects.get_or_create(
            business=b,
            user=user,
            defaults={"role": BusinessMember.ROLE_OWNER, "is_active": True},
        )

        # Ensure correct role + permissions even if somehow existed
        m.role = BusinessMember.ROLE_OWNER
        m.is_active = True
        if hasattr(m, "apply_role_defaults"):
            m.apply_role_defaults()
        m.save()

        m = (
            BusinessMember.objects.filter(id=m.id)
            .select_related("business")
            .first()
        )

        payload = self._format_membership(request, m) if m else {}
        if not payload:
            return Response({"detail": "Failed to create business membership"}, status=500)

        return Response(payload, status=status.HTTP_201_CREATED)
