from __future__ import annotations

from django.db.models import Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models import Notification, PlatformNewsItem
from user_accounts.serializers.notifications import NotificationSerializer, PlatformNewsItemSerializer
from user_accounts.services.sync_alerts import sync_alerts_for_user


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """User-scoped internal Inbox + central SYNC Alert Center."""
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Notification.objects.filter(recipient=self.request.user).order_by("-created_at")

        n_type = (self.request.query_params.get("type") or "").strip().upper()
        unread = (self.request.query_params.get("unread") or "").strip().lower()
        archived = (self.request.query_params.get("archived") or "").strip().lower()
        q = (self.request.query_params.get("q") or "").strip()
        source = (self.request.query_params.get("source") or "").strip().upper()
        severity = (self.request.query_params.get("severity") or "").strip().upper()
        sync_only = (self.request.query_params.get("sync_alerts") or "").strip().lower()

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
        if source:
            qs = qs.filter(data__source=source)
        if severity:
            qs = qs.filter(data__severity=severity)
        if sync_only in ("1", "true", "yes"):
            qs = qs.filter(data__sync_alert=True)
        return qs

    @action(detail=True, methods=["post"], url_path="read")
    def mark_read(self, request, pk=None):
        n = self.get_object()
        n.mark_read()
        return Response(NotificationSerializer(n).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="archive")
    def archive(self, request, pk=None):
        n = self.get_object()
        n.archive()
        return Response(NotificationSerializer(n).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="unarchive")
    def unarchive(self, request, pk=None):
        n = self.get_object()
        n.unarchive()
        return Response(NotificationSerializer(n).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="mark-all-read")
    def mark_all_read(self, request):
        now = timezone.now()
        Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True, read_at=now)
        return Response({"ok": True}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        c = Notification.objects.filter(recipient=request.user, is_read=False, archived_at__isnull=True).count()
        sync_count = Notification.objects.filter(recipient=request.user, is_read=False, archived_at__isnull=True, data__sync_alert=True).count()
        return Response({"unread": c, "sync_alerts": sync_count}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        qs = Notification.objects.filter(recipient=request.user, archived_at__isnull=True, data__sync_alert=True)
        by_source = {}
        by_severity = {}
        for source in ("FINANCE", "HEALTH", "CALENDAR", "TRAVEL", "SOCIAL", "PM", "SYSTEM"):
            count = qs.filter(data__source=source).count()
            if count:
                by_source[source] = count
        for severity in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
            count = qs.filter(data__severity=severity).count()
            if count:
                by_severity[severity] = count
        return Response({
            "total": qs.count(),
            "unread": qs.filter(is_read=False).count(),
            "by_source": by_source,
            "by_severity": by_severity,
        })

    @action(detail=False, methods=["post"], url_path="refresh-sync-alerts")
    def refresh_sync_alerts(self, request):
        result = sync_alerts_for_user(request.user, send_email=False)
        return Response({"ok": True, **result}, status=status.HTTP_200_OK)


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
