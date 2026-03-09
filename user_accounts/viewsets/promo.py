from __future__ import annotations

from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from user_accounts.models import PromoCode, PromoRedemption


def _is_platform_admin(user) -> bool:
    return bool(getattr(user, "is_platform_admin", False) or getattr(user, "is_superuser", False))


from user_accounts.serializers.promo import PromoCodeSerializer, PromoRedemptionSerializer


class PromoCodeViewSet(viewsets.ModelViewSet):
    serializer_class = PromoCodeSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Platform admin only
        if not _is_platform_admin(self.request.user):
            return PromoCode.objects.none()
        return PromoCode.objects.all().order_by("-created_at")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class PromoRedemptionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PromoRedemptionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if not _is_platform_admin(self.request.user):
            return PromoRedemption.objects.none()
        return PromoRedemption.objects.select_related("promo", "user", "business").all().order_by("-redeemed_at")
