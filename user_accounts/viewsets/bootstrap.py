# user_accounts/viewsets/bootstrap.py
from __future__ import annotations

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from user_accounts.models import Business, BusinessMember


class BootstrapMyBusinessAPIView(APIView):
    """
    POST /api/v1/bootstrap/my-business/
    Creates a Business owned by the current user if none exists.
    Also ensures a BusinessMember record exists.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        u = request.user

        # If they already own a business, return it
        existing = Business.objects.filter(owner=u, is_active=True).first()
        if existing:
            BusinessMember.objects.get_or_create(
                business=existing,
                user=u,
                defaults={"role": BusinessMember.ROLE_OWNER, "is_active": True},
            )
            return Response(
                {"detail": "Business already exists.", "business_id": existing.id, "business_name": existing.name},
                status=status.HTTP_200_OK,
            )

        name = (request.data.get("name") or "").strip() or "Jacob's Business"

        biz = Business.objects.create(
            owner=u,
            name=name,
            is_active=True,
        )

        BusinessMember.objects.create(
            business=biz,
            user=u,
            role=BusinessMember.ROLE_OWNER,
            is_active=True,
            can_manage_team=True,
            can_manage_settings=True,
            can_view_financials=True,
            can_manage_invoices=True,
        )

        return Response(
            {"detail": "Business created.", "business_id": biz.id, "business_name": biz.name},
            status=status.HTTP_201_CREATED,
        )
