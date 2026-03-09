from __future__ import annotations

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models import FavoriteBusiness, Business
from user_accounts.serializers.favorites import (
    FavoriteBusinessSerializer,
    FavoriteBusinessClaimSerializer,
)


class MeFavoriteBusinessViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    Me-scoped saved businesses.

    Routes:
      GET    /me/favorites/businesses/
      POST   /me/favorites/businesses/          { business_id, nickname? }
      POST   /me/favorites/businesses/claim/    { code, nickname? }
      DELETE /me/favorites/businesses/<id>/
    """
    serializer_class = FavoriteBusinessSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            FavoriteBusiness.objects.filter(customer=self.request.user)
            .select_related("business")
            .order_by("-created_at")
        )

    def create(self, request, *args, **kwargs):
        ser = FavoriteBusinessSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        business = ser.validated_data["business"]
        nickname = ser.validated_data.get("nickname", "") or ""

        obj, created = FavoriteBusiness.objects.get_or_create(
            customer=request.user,
            business=business,
            defaults={"nickname": nickname},
        )
        if not created and nickname and obj.nickname != nickname:
            obj.nickname = nickname
            obj.save(update_fields=["nickname"])

        return Response(FavoriteBusinessSerializer(obj).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="claim")
    def claim(self, request):
        """
        Claim a business card by QR/paste code.

        POST /me/favorites/businesses/claim/
        { "code": "SW-xxxx", "nickname": "" }
        """
        ser = FavoriteBusinessClaimSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        code = (ser.validated_data.get("code") or "").strip()
        nickname = ser.validated_data.get("nickname", "") or ""

        try:
            business = Business.objects.get(business_card_code=code)
        except Business.DoesNotExist:
            return Response({"detail": "Invalid business card code."}, status=status.HTTP_400_BAD_REQUEST)

        obj, created = FavoriteBusiness.objects.get_or_create(
            customer=request.user,
            business=business,
            defaults={"nickname": nickname},
        )
        if not created and nickname and obj.nickname != nickname:
            obj.nickname = nickname
            obj.save(update_fields=["nickname"])

        return Response(FavoriteBusinessSerializer(obj).data, status=status.HTTP_201_CREATED)