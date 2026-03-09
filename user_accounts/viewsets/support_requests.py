# backend/user_accounts/viewsets/support_requests.py
from __future__ import annotations

from django.db.models import Q
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models.support_requests import SupportRequest
from user_accounts.serializers.support_requests import (
    SupportRequestHandleSerializer,
    SupportRequestSerializer,
)


def _is_platform_admin(user) -> bool:
    return bool(getattr(user, "is_platform_admin", False) or getattr(user, "is_superuser", False))


class SupportRequestViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """
    ✅ Customer/Business-facing Support Requests

    POST   /api/v1/support/requests/
    GET    /api/v1/support/requests/
    GET    /api/v1/support/requests/<id>/

    Notes:
    - Users can only see their own requests.
    - Creating a request optionally includes business_id (for faster routing).
    - Requests are routed to SyncWorks Support (platform console reads the same table).
    """

    permission_classes = [IsAuthenticated]
    serializer_class = SupportRequestSerializer

    def get_queryset(self):
        qs = SupportRequest.objects.filter(requester=self.request.user).order_by("-created_at")

        qp = self.request.query_params

        status_val = (qp.get("status") or "").strip()
        if status_val:
            qs = qs.filter(status=status_val)

        kind = (qp.get("kind") or "").strip()
        if kind:
            qs = qs.filter(kind=kind)

        business_id = (qp.get("business_id") or "").strip()
        if business_id:
            try:
                qs = qs.filter(business_id=int(business_id))
            except Exception:
                pass

        q = (qp.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(body__icontains=q))

        return qs

    def create(self, request, *args, **kwargs):
        data = request.data or {}

        title = (data.get("title") or "").strip()
        body = (data.get("body") or "").strip()
        kind = (data.get("kind") or SupportRequest.Kind.OTHER).strip() or SupportRequest.Kind.OTHER

        # business_id is optional (allows locked users to contact support about billing/access)
        business_id = data.get("business_id", None)
        business_id_int = None
        if business_id not in (None, "", 0, "0"):
            try:
                business_id_int = int(str(business_id).strip())
            except Exception:
                return Response({"detail": "business_id must be an integer."}, status=status.HTTP_400_BAD_REQUEST)

        if not title:
            title = "Message to SyncWorks Support"

        if not body:
            return Response({"detail": "body is required."}, status=status.HTTP_400_BAD_REQUEST)

        # clamp to model limits
        title = title[:140]

        obj = SupportRequest.objects.create(
            requester=request.user,
            role=(getattr(request.user, "role", "") or "")[:32],
            business_id=business_id_int,
            kind=kind,
            title=title,
            body=body,
            status=SupportRequest.Status.OPEN,
        )

        return Response(SupportRequestSerializer(obj).data, status=status.HTTP_201_CREATED)


class PlatformSupportRequestViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """
    ✅ SyncWorks Support Console (Platform Admin Inbox)

    GET    /api/v1/platform/support/requests/
    GET    /api/v1/platform/support/requests/<id>/
    PATCH  /api/v1/platform/support/requests/<id>/            (platform admin only)
    POST   /api/v1/platform/support/requests/<id>/close/      (platform admin only)
    POST   /api/v1/platform/support/requests/<id>/open/       (platform admin only)

    Filtering:
    - role, status, kind, business_id, q
    """

    permission_classes = [IsAuthenticated]
    serializer_class = SupportRequestSerializer

    def get_queryset(self):
        qs = SupportRequest.objects.all().order_by("-created_at")

        # ✅ platform admin only
        if not _is_platform_admin(self.request.user):
            return SupportRequest.objects.none()

        qp = self.request.query_params

        role = (qp.get("role") or "").strip()
        if role:
            qs = qs.filter(role=role)

        status_val = (qp.get("status") or "").strip()
        if status_val:
            qs = qs.filter(status=status_val)

        kind = (qp.get("kind") or "").strip()
        if kind:
            qs = qs.filter(kind=kind)

        business_id = (qp.get("business_id") or "").strip()
        if business_id:
            try:
                qs = qs.filter(business_id=int(business_id))
            except Exception:
                pass

        q = (qp.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(title__icontains=q)
                | Q(body__icontains=q)
                | Q(requester__email__icontains=q)
            )

        return qs

    def get_serializer_class(self):
        if self.action in ("partial_update", "update"):
            return SupportRequestHandleSerializer
        return SupportRequestSerializer

    def update(self, request, *args, **kwargs):
        if not _is_platform_admin(request.user):
            return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        if not _is_platform_admin(request.user):
            return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)

        obj = self.get_object()
        ser = self.get_serializer(obj, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)

        updated_fields = []
        if "status" in ser.validated_data:
            obj.status = ser.validated_data["status"]
            updated_fields.append("status")

            # if changing to CLOSED, mark handled
            if obj.status == SupportRequest.Status.CLOSED:
                obj.handled_by = request.user
                obj.handled_at = timezone.now()
                updated_fields += ["handled_by", "handled_at"]

        if updated_fields:
            obj.save(update_fields=updated_fields + ["updated_at"])

        return Response(SupportRequestSerializer(obj).data)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        if not _is_platform_admin(request.user):
            return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)

        obj = self.get_object()
        obj.status = SupportRequest.Status.CLOSED
        obj.handled_by = request.user
        obj.handled_at = timezone.now()
        obj.save(update_fields=["status", "handled_by", "handled_at", "updated_at"])
        return Response(SupportRequestSerializer(obj).data)

    @action(detail=True, methods=["post"])
    def open(self, request, pk=None):
        if not _is_platform_admin(request.user):
            return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)

        obj = self.get_object()
        obj.status = SupportRequest.Status.OPEN
        obj.handled_by = None
        obj.handled_at = None
        obj.save(update_fields=["status", "handled_by", "handled_at", "updated_at"])
        return Response(SupportRequestSerializer(obj).data)