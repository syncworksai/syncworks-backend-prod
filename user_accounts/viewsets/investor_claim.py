# backend/user_accounts/viewsets/investor_claim.py
from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import PMInvestor, PMInvestorConnection


class InvestorClaimAPIView(APIView):
    """
    Investor-side claim (NO X-Business-Id).
    Investor enters connect_code (issued by PM business).
    Links:
      - PMInvestor.user = request.user (if empty)
      - PMInvestorConnection.status = ACCEPTED
      - accepted_at = now

    POST /api/v1/investor/claim/
    Body: { "connect_code": "..." }
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        code = str((request.data or {}).get("connect_code") or "").strip()
        if not code:
            raise ValidationError({"connect_code": "connect_code is required."})

        conn = PMInvestorConnection.objects.select_related("investor").filter(connect_code=code).first()
        if not conn:
            raise ValidationError({"detail": "Invalid connect_code."})

        if (conn.status or "").upper() == "REVOKED":
            raise ValidationError({"detail": "This connection was revoked."})

        inv: PMInvestor = conn.investor

        with transaction.atomic():
            # If investor already linked to someone else -> block
            if getattr(inv, "user_id", None) and inv.user_id != request.user.id:
                raise ValidationError({"detail": "This investor profile is already claimed by another user."})

            # Link investor to this user
            if getattr(inv, "user_id", None) in (None, 0):
                inv.user = request.user
                if hasattr(inv, "is_active") and inv.is_active is False:
                    inv.is_active = True
                inv.save()

            # Accept connection
            if (conn.status or "").upper() != "ACCEPTED":
                conn.status = "ACCEPTED"
                if hasattr(conn, "accepted_at"):
                    conn.accepted_at = timezone.now()
                conn.save()

        return Response(
            {
                "ok": True,
                "business_id": conn.business_id,
                "investor_id": inv.id,
                "status": conn.status,
            },
            status=status.HTTP_200_OK,
        )
