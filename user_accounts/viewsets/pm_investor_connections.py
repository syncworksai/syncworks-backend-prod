# backend/user_accounts/viewsets/pm_investor_connections.py
from __future__ import annotations

from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models.business import Business
from user_accounts.models.pm_investor_connection import PMInvestorConnection
from user_accounts.serializers.pm_investor_connections import (
    PMInvestorConnectByCodeSerializer,
    PMInvestorConnectionSerializer,
)


def _get_business_from_header(request) -> Business:
    raw = request.headers.get("X-Business-Id") or request.META.get("HTTP_X_BUSINESS_ID")
    if not raw:
        raise ValidationError({"detail": "Missing X-Business-Id header."})
    try:
        bid = int(raw)
    except Exception:
        raise ValidationError({"detail": "Invalid X-Business-Id header."})

    from user_accounts.models.business import Business  # local import to avoid cycles
    try:
        return Business.objects.get(id=bid)
    except Business.DoesNotExist:
        raise ValidationError({"detail": "Business not found."})


def _require_business_access(user, business: Business) -> None:
    from user_accounts.models.business import BusinessMember

    if business.owner_id == user.id:
        return
    if BusinessMember.objects.filter(business=business, user=user, is_active=True).exists():
        return
    raise PermissionDenied("You do not have access to this business.")


class PMInvestorConnectionViewSet(viewsets.ModelViewSet):
    """
    PM-side: list/manage investor connections for THIS business.
    Investor-side: accept a connection via connect_code (action below).
    """

    permission_classes = [IsAuthenticated]
    serializer_class = PMInvestorConnectionSerializer

    def get_queryset(self):
        biz = _get_business_from_header(self.request)
        _require_business_access(self.request.user, biz)
        return PMInvestorConnection.objects.filter(business_id=biz.id).select_related("investor").order_by("-id")

    def perform_create(self, serializer):
        biz = _get_business_from_header(self.request)
        _require_business_access(self.request.user, biz)
        serializer.save(business_id=biz.id)

    @action(detail=False, methods=["POST"], url_path="connect-by-code", permission_classes=[IsAuthenticated])
    def connect_by_code(self, request):
        """
        Investor-side: logged-in user enters connect_code to accept PM business connection.
        Requires that user has already claimed an investor profile (PMInvestor.user = request.user).
        """
        if not hasattr(request.user, "pm_investor_profile"):
            raise ValidationError({"detail": "No investor profile linked to this user. Claim your investor first."})

        ser = PMInvestorConnectByCodeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        code = (ser.validated_data.get("connect_code") or "").strip()
        try:
            conn = PMInvestorConnection.objects.select_related("investor").get(connect_code=code)
        except PMInvestorConnection.DoesNotExist:
            raise ValidationError({"connect_code": "Invalid connect code."})

        if conn.investor.user_id != request.user.id:
            raise PermissionDenied("This connection does not belong to your investor profile.")

        if conn.status != PMInvestorConnection.Status.ACCEPTED:
            conn.status = PMInvestorConnection.Status.ACCEPTED
            conn.accepted_at = timezone.now()
            conn.revoked_at = None
            conn.save(update_fields=["status", "accepted_at", "revoked_at"])

        return Response(PMInvestorConnectionSerializer(conn).data, status=status.HTTP_200_OK)
