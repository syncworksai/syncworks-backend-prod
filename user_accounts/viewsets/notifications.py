from __future__ import annotations

from django.db.models import Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models import Notification, PlatformNewsItem
from user_accounts.serializers.notifications import NotificationSerializer, PlatformNewsItemSerializer


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Inbox endpoints.

    Supports query params:
      - type=SYSTEM|TICKET|BROADCAST|BILLING|MESSAGE|REMINDER|PROMO
      - unread=true|false
      - archived=true|false
      - q=search text across title/body
    """
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Notification.objects.filter(recipient=self.request.user).order_by("-created_at")

        n_type = (self.request.query_params.get("type") or "").strip().upper()
        unread = (self.request.query_params.get("unread") or "").strip().lower()
        archived = (self.request.query_params.get("archived") or "").strip().lower()
        q = (self.request.query_params.get("q") or "").strip()

        if n_type:
            qs = qs.filter(type=n_type)

        if unread in ("1", "true", "yes"):
            qs = qs.filter(is_read=False)
        elif unread in ("0", "false", "no"):
            qs = qs.filter(is_read=True)

        if archived in ("1", "true", "yes"):
            qs = qs.filter(archived_at__isnull=False)
        elif archived in ("0", "false", "no"):
            qs = qs.filter(archived_at__isnull=True)

        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(body__icontains=q))

        return qs

    @action(detail=True, methods=["post"], url_path="read")
    def mark_read(self, request, pk=None):
        n = self.get_object()
        if not n.is_read:
            n.is_read = True
            n.read_at = timezone.now()
            n.save(update_fields=["is_read", "read_at"])
        return Response(NotificationSerializer(n).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="archive")
    def archive(self, request, pk=None):
        n = self.get_object()
        if not n.archived_at:
            n.archived_at = timezone.now()
            n.save(update_fields=["archived_at"])
        return Response(NotificationSerializer(n).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="unarchive")
    def unarchive(self, request, pk=None):
        n = self.get_object()
        if n.archived_at:
            n.archived_at = None
            n.save(update_fields=["archived_at"])
        return Response(NotificationSerializer(n).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="mark-all-read")
    def mark_all_read(self, request):
        now = timezone.now()
        Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True, read_at=now)
        return Response({"ok": True}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        c = Notification.objects.filter(recipient=request.user, is_read=False, archived_at__isnull=True).count()
        return Response({"unread": c}, status=status.HTTP_200_OK)


class MeNewsReelViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PlatformNewsItemSerializer
    permission_classes = [IsAuthenticated]

    def _get_user_zip(self) -> str:
        u = self.request.user
        try:
            zp = getattr(u, "customer_profile", None)
            if zp and getattr(zp, "zip_code", None):
                return str(zp.zip_code).strip()
        except Exception:
            pass
        return ""

    def _get_user_scope(self) -> str:
        r = (getattr(self.request.user, "role", "") or "").upper()
        if r in ("CUSTOMER", "SBO", "PM"):
            return r
        return "ALL"

    def get_queryset(self):
        now = timezone.now()
        user_zip = self._get_user_zip()
        user_scope = self._get_user_scope()

        qs = (
            PlatformNewsItem.objects.filter(is_active=True)
            .filter(Q(starts_at__isnull=True) | Q(starts_at__lte=now))
            .filter(Q(ends_at__isnull=True) | Q(ends_at__gte=now))
            .order_by("-created_at")
        )

        qs = qs.filter(Q(target_scope="ALL") | Q(target_scope=user_scope))

        if user_zip:
            qs = qs.filter(Q(target_zip_codes=[]) | Q(target_zip_codes__contains=[user_zip]))
        else:
            qs = qs.filter(target_zip_codes=[])

        return qs
