# backend/user_accounts/viewsets/business.py
from __future__ import annotations

from django.db.models import Q
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models.business import Business, BusinessMember
from user_accounts.serializers.business import BusinessSerializer, BusinessMemberSerializer


def _is_platform_admin(user) -> bool:
    return bool(
        getattr(user, "is_platform_admin", False)
        or getattr(user, "is_superuser", False)
        or getattr(user, "is_staff", False)
    )


class BusinessViewSet(viewsets.ModelViewSet):
    serializer_class = BusinessSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user

        if _is_platform_admin(user):
            return Business.objects.all().order_by("-created_at")

        return (
            Business.objects.filter(
                Q(owner=user) | Q(members__user=user, members__is_active=True)
            )
            .distinct()
            .order_by("-created_at")
        )

    def perform_create(self, serializer):
        business = serializer.save(owner=self.request.user)

        # ensure OWNER membership
        membership, created = BusinessMember.objects.get_or_create(
            business=business,
            user=self.request.user,
            defaults={"role": BusinessMember.ROLE_OWNER, "is_active": True},
        )
        if created or membership.role != BusinessMember.ROLE_OWNER:
            membership.role = BusinessMember.ROLE_OWNER
            membership.is_active = True
            if hasattr(membership, "apply_role_defaults"):
                membership.apply_role_defaults()
            membership.save()

    @action(detail=False, methods=["get"], url_path="me")
    def me(self, request):
        """
        Paginated "my businesses" list (same shape as /businesses/)
        """
        qs = self.get_queryset()
        page = self.paginate_queryset(qs)
        if page is not None:
            ser = self.get_serializer(page, many=True)
            return self.get_paginated_response(ser.data)

        ser = self.get_serializer(qs, many=True)
        return Response(ser.data)


class BusinessMemberViewSet(viewsets.ModelViewSet):
    serializer_class = BusinessMemberSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if _is_platform_admin(user):
            return BusinessMember.objects.all().order_by("-created_at")
        return BusinessMember.objects.filter(user=user).order_by("-created_at")
