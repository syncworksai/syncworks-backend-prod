# backend/user_accounts/viewsets/businesses.py
from __future__ import annotations

from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models import Business, BusinessMember


class BusinessLiteSerializer(serializers.ModelSerializer):
    logo_url = serializers.SerializerMethodField()

    class Meta:
        model = Business
        fields = [
            "id",
            "name",
            "base_zip",
            "is_active",
            "accepts_marketplace_tickets",
            "logo_url",
        ]

    def get_logo_url(self, obj: Business):
        try:
            if obj.logo and hasattr(obj.logo, "url"):
                request = self.context.get("request")
                if request:
                    return request.build_absolute_uri(obj.logo.url)
                return obj.logo.url
        except Exception:
            return None
        return None


class BusinessViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/v1/businesses/
      - Platform admin: all businesses
      - Normal users: businesses they own OR are a member of

    GET /api/v1/businesses/me/
      - explicit alias for “my businesses”
    """

    permission_classes = [IsAuthenticated]
    serializer_class = BusinessLiteSerializer

    def list(self, request, *args, **kwargs):
        u = request.user

        if getattr(u, "is_platform_admin", False) or getattr(u, "is_superuser", False) or getattr(u, "is_staff", False):
            qs = Business.objects.all().order_by("name")
            return Response(BusinessLiteSerializer(qs, many=True, context={"request": request}).data)

        member_business_ids = BusinessMember.objects.filter(user=u).values_list("business_id", flat=True)

        try:
            qs = Business.objects.filter(owner=u).order_by("name")
            qs = (qs | Business.objects.filter(id__in=member_business_ids)).distinct().order_by("name")
        except Exception:
            qs = Business.objects.filter(id__in=member_business_ids).distinct().order_by("name")

        return Response(BusinessLiteSerializer(qs, many=True, context={"request": request}).data)

    @action(detail=False, methods=["get"], url_path="me")
    def me(self, request):
        return self.list(request)
