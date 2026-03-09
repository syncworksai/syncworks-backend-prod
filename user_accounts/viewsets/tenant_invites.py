# backend/user_accounts/viewsets/tenant_invites.py
from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import PMInvite, PMTenant


def _has_field(model, field_name: str) -> bool:
    try:
        model._meta.get_field(field_name)
        return True
    except Exception:
        return False


class TenantInviteAcceptAPIView(APIView):
    """
    Tenant Portal - Accept Invite
    POST: { "code": "<invite_code>" }

    Links:
      request.user <-> PMTenant (if PMTenant has user field)
      PMTenant <-> PMUnit (via invite.unit)
      PMTenant.email (if field exists)

    Marks invite accepted (status/accepted_at etc, based on schema).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        data = request.data or {}
        code = (data.get("code") or "").strip()

        if not code:
            return Response({"detail": "Invite code is required."}, status=status.HTTP_400_BAD_REQUEST)

        now = timezone.now()

        # IMPORTANT: PMInvite uses `code` (NOT token)
        invite = PMInvite.objects.filter(code=code).select_related("unit").first()
        if not invite:
            return Response({"detail": "Invalid invite code."}, status=status.HTTP_404_NOT_FOUND)

        # Expired?
        expires_at = getattr(invite, "expires_at", None)
        if expires_at and expires_at <= now:
            return Response({"detail": "Invite has expired."}, status=status.HTTP_400_BAD_REQUEST)

        # Already accepted?
        if getattr(invite, "status", "").lower() in ("accepted", "complete", "completed"):
            return Response({"detail": "Invite already accepted."}, status=status.HTTP_200_OK)

        unit = getattr(invite, "unit", None)
        if not unit:
            return Response({"detail": "Invite is missing a unit link."}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user
        user_email = (getattr(user, "email", "") or "").strip().lower()
        invite_email = (getattr(invite, "email", "") or "").strip().lower()

        # Optional: if invite has an email and user has an email, enforce match
        if invite_email and user_email and invite_email != user_email:
            return Response(
                {"detail": "This invite was sent to a different email address."},
                status=status.HTTP_403_FORBIDDEN,
            )

        with transaction.atomic():
            # 1) Mark invite accepted
            if _has_field(PMInvite, "accepted_at"):
                invite.accepted_at = now

            if _has_field(PMInvite, "status"):
                invite.status = "accepted"

            if _has_field(PMInvite, "updated_at"):
                invite.updated_at = now

            invite.save()

            # 2) Find or create PMTenant for this unit/email
            # We try best-effort matching depending on schema.
            tenant_qs = PMTenant.objects.filter(unit=unit)

            # If PMTenant has email fields, try to match invite email/user email
            email_field = None
            for f in ["email", "tenant_email"]:
                if _has_field(PMTenant, f):
                    email_field = f
                    break

            if email_field and invite_email:
                tenant_qs = tenant_qs.filter(**{email_field: invite_email})

            tenant = tenant_qs.first()

            if not tenant:
                create_kwargs = {"unit": unit}

                # If tenant has a business field, set from unit/business
                if _has_field(PMTenant, "business_id") and hasattr(unit, "business_id"):
                    create_kwargs["business_id"] = unit.business_id
                elif _has_field(PMTenant, "business") and hasattr(unit, "business_id"):
                    create_kwargs["business_id"] = unit.business_id

                # Set email if possible
                if email_field:
                    create_kwargs[email_field] = invite_email or user_email or ""

                tenant = PMTenant.objects.create(**create_kwargs)

            # 3) Link tenant to user account if schema supports it
            if _has_field(PMTenant, "user"):
                tenant.user = user
                tenant.save()

        return Response(
            {
                "ok": True,
                "invite_id": invite.id,
                "unit_id": unit.id,
                "tenant_id": tenant.id,
                "message": "Invite accepted and tenant linked.",
            },
            status=status.HTTP_200_OK,
        )
