# backend/user_accounts/viewsets/pm_investors.py
from __future__ import annotations

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models.business import Business
from user_accounts.models.pm_investor import PMInvestor
from user_accounts.models.pm_investor_connection import PMInvestorConnection
from user_accounts.serializers.pm_investors import PMInvestorClaimSerializer, PMInvestorSerializer


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


class PMInvestorViewSet(viewsets.ModelViewSet):
    """
    PM-side: manage investors under this PM company (business header).
    This does NOT mean the investor is an app-user yet.

    We automatically create a PMInvestorConnection (PENDING) when an investor is created via this endpoint.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = PMInvestorSerializer

    def get_queryset(self):
        biz = _get_business_from_header(self.request)
        _require_business_access(self.request.user, biz)

        # Investors connected to this business (any status)
        investor_ids = PMInvestorConnection.objects.filter(business_id=biz.id).values_list("investor_id", flat=True)
        return PMInvestor.objects.filter(id__in=investor_ids).order_by("-updated_at", "-id")

    def perform_create(self, serializer):
        biz = _get_business_from_header(self.request)
        _require_business_access(self.request.user, biz)

        inv = serializer.save()
        PMInvestorConnection.objects.get_or_create(
            investor=inv,
            business_id=biz.id,
            defaults={"status": PMInvestorConnection.Status.PENDING},
        )

    @action(detail=False, methods=["POST"], url_path="claim", permission_classes=[IsAuthenticated])
    def claim(self, request):
        """
        Investor-side: logged-in user claims a PMInvestor by claim_code.
        This is used when investor logs in from main Login.jsx then enters claim code.
        """
        ser = PMInvestorClaimSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        code = (ser.validated_data.get("claim_code") or "").strip()
        try:
            inv = PMInvestor.objects.get(claim_code=code)
        except PMInvestor.DoesNotExist:
            raise ValidationError({"claim_code": "Invalid claim code."})

        if inv.user_id and inv.user_id != request.user.id:
            raise ValidationError({"detail": "This investor profile is already claimed."})

        inv.user = request.user
        inv.mark_claimed()
        inv.save(update_fields=["user", "claimed_at", "updated_at"])

        return Response(PMInvestorSerializer(inv).data, status=status.HTTP_200_OK)
