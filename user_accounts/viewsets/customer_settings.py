# backend/user_accounts/viewsets/customer_settings.py
from __future__ import annotations

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models.customer_settings import CustomerSettings
from user_accounts.serializers.customer_settings import (
    CustomerSettingsSerializer,
    CustomerSettingsUpdateSerializer,
)


class CustomerSettingsViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def _get_or_create(self, user) -> CustomerSettings:
        obj = CustomerSettings.objects.filter(user_id=user.id).first()
        if obj:
            return obj
        return CustomerSettings.objects.create(user=user)

    @action(detail=False, methods=["get", "patch"], url_path="me")
    def me(self, request):
        obj = self._get_or_create(request.user)

        if request.method.lower() == "get":
            return Response(CustomerSettingsSerializer(obj).data, status=status.HTTP_200_OK)

        # Allow updating basic user fields in the same request (optional)
        # This keeps UI clean.
        u = request.user
        first_name = request.data.get("first_name", None)
        last_name = request.data.get("last_name", None)

        dirty = False
        if first_name is not None:
            u.first_name = (first_name or "").strip()
            dirty = True
        if last_name is not None:
            u.last_name = (last_name or "").strip()
            dirty = True
        if dirty:
            u.save(update_fields=["first_name", "last_name"])

        write = CustomerSettingsUpdateSerializer(obj, data=request.data, partial=True)
        write.is_valid(raise_exception=True)
        write.save()

        return Response(CustomerSettingsSerializer(obj).data, status=status.HTTP_200_OK)
