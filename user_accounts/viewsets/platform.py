# user_accounts/viewsets/platform.py
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count
from django.utils import timezone

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet

from user_accounts.permissions.god_mode import IsGodMode
from user_accounts.models import (
    Business,
    Ticket,
    Invoice,
    PlatformBillingProfile,
    Notification,
    PlatformNewsItem,
)
from user_accounts.serializers.platform_console import (
    PlatformUserSerializer,
    PlatformBusinessSerializer,
)
from user_accounts.serializers.notifications import PlatformNewsItemSerializer

User = get_user_model()


# -------------------------
# ME / KPIS
# -------------------------
class PlatformMeAPIView(APIView):
    permission_classes = [IsAuthenticated, IsGodMode]

    def get(self, request):
        u = request.user
        return Response(
            {
                "id": u.id,
                "email": u.email,
                "role": getattr(u, "role", None),
                "first_name": getattr(u, "first_name", ""),
                "last_name": getattr(u, "last_name", ""),
                "is_platform_admin": getattr(u, "is_platform_admin", False),
                "is_staff": getattr(u, "is_staff", False),
                "is_superuser": getattr(u, "is_superuser", False),
            }
        )


class PlatformKpisAPIView(APIView):
    """
    Returns what PlatformDashboard.jsx expects.
    """
    permission_classes = [IsAuthenticated, IsGodMode]

    def get(self, request):
        today = timezone.localdate()
        start_30 = today - timedelta(days=30)

        users_total = User.objects.count()
        businesses_total = Business.objects.count()
        tickets_total = Ticket.objects.count()
        invoices_total = Invoice.objects.count()

        signups_last_30_days = User.objects.filter(date_joined__date__gte=start_30, date_joined__date__lte=today).count()

        # Billing snapshots
        profiles = PlatformBillingProfile.objects.all()
        businesses_with_card_on_file = profiles.filter(stripe_setup_complete=True).count()
        businesses_locked = profiles.filter(is_locked=True).count()

        # Simple MRR estimate (tweak later):
        # assume "card on file" roughly equals active paying business at $19.99
        # (you can replace with real subscription data later)
        mrr_estimate_cents = int(businesses_with_card_on_file * 1999)

        return Response(
            {
                "users_total": users_total,
                "businesses_total": businesses_total,
                "tickets_total": tickets_total,
                "invoices_total": invoices_total,
                "signups_last_30_days": signups_last_30_days,
                "businesses_with_card_on_file": businesses_with_card_on_file,
                "businesses_locked": businesses_locked,
                "mrr_estimate_cents": mrr_estimate_cents,
            }
        )


class PlatformKpiTimeseriesViewSet(viewsets.ViewSet):
    """
    GET /api/v1/platform/kpis/timeseries/?days=30
    """
    permission_classes = [IsAuthenticated, IsGodMode]

    def list(self, request):
        days = int(request.query_params.get("days") or 30)
        days = max(7, min(days, 365))

        today = timezone.localdate()
        start = today - timedelta(days=days - 1)

        series = {
            start + timedelta(days=i): {"signups": 0, "businesses_created": 0, "locked_businesses": 0}
            for i in range(days)
        }

        users = (
            User.objects.filter(date_joined__date__gte=start, date_joined__date__lte=today)
            .values("date_joined__date")
            .annotate(c=Count("id"))
        )
        for row in users:
            d = row["date_joined__date"]
            if d in series:
                series[d]["signups"] = row["c"]

        biz = (
            Business.objects.filter(created_at__date__gte=start, created_at__date__lte=today)
            .values("created_at__date")
            .annotate(c=Count("id"))
        )
        for row in biz:
            d = row["created_at__date"]
            if d in series:
                series[d]["businesses_created"] = row["c"]

        locks = (
            PlatformBillingProfile.objects.filter(locked_at__date__gte=start, locked_at__date__lte=today)
            .values("locked_at__date")
            .annotate(c=Count("id"))
        )
        for row in locks:
            d = row["locked_at__date"]
            if d in series:
                series[d]["locked_businesses"] = row["c"]

        out = []
        for d in sorted(series.keys()):
            out.append(
                {
                    "date": d,
                    "signups": series[d]["signups"],
                    "businesses_created": series[d]["businesses_created"],
                    "locked_businesses": series[d]["locked_businesses"],
                }
            )
        return Response(out, status=status.HTTP_200_OK)


# -------------------------
# DIRECTORIES / ACTIONS
# -------------------------
class PlatformUsersViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated, IsGodMode]
    serializer_class = PlatformUserSerializer

    def get_queryset(self):
        qs = User.objects.all().order_by("-date_joined")
        q = (self.request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(email__icontains=q)
        return qs


class PlatformBusinessesViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated, IsGodMode]
    serializer_class = PlatformBusinessSerializer

    def get_queryset(self):
        qs = Business.objects.all().order_by("-created_at")
        q = (self.request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(name__icontains=q)
        return qs

    @action(detail=True, methods=["post"], url_path="lock")
    def lock_business(self, request, pk=None):
        reason = (request.data.get("reason") or "Locked by platform admin").strip()
        biz = self.get_object()
        profile, _ = PlatformBillingProfile.objects.get_or_create(business=biz)
        profile.is_locked = True
        profile.lock_reason = reason
        profile.locked_at = timezone.now()
        profile.save(update_fields=["is_locked", "lock_reason", "locked_at"])
        return Response(
            {"detail": "Business locked.", "business_id": biz.id, "lock_reason": profile.lock_reason},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="unlock")
    def unlock_business(self, request, pk=None):
        biz = self.get_object()
        profile, _ = PlatformBillingProfile.objects.get_or_create(business=biz)
        profile.is_locked = False
        profile.lock_reason = ""
        profile.locked_at = None
        profile.save(update_fields=["is_locked", "lock_reason", "locked_at"])
        return Response({"detail": "Business unlocked.", "business_id": biz.id}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="message-owner")
    def message_owner(self, request, pk=None):
        """
        POST /platform/businesses/:id/message-owner/
        { "title": "...", "body": "..." }
        Sends notification to all active members (best-effort).
        """
        biz = self.get_object()
        title = (request.data.get("title") or "").strip()
        body = (request.data.get("body") or "").strip()
        if not title or not body:
            return Response({"detail": "title and body are required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            member_user_ids = list(biz.members.filter(is_active=True).values_list("user_id", flat=True))
        except Exception:
            member_user_ids = []

        if not member_user_ids:
            return Response({"detail": "No active members found for this business."}, status=status.HTTP_400_BAD_REQUEST)

        Notification.objects.bulk_create(
            [
                Notification(
                    recipient_id=uid,
                    actor=request.user,
                    type=Notification.TYPE_SYSTEM,
                    title=title,
                    body=body,
                    data={"business_id": biz.id},
                )
                for uid in member_user_ids
            ],
            batch_size=500,
        )
        return Response({"detail": "Message sent.", "recipients": len(member_user_ids)}, status=status.HTTP_201_CREATED)


class PlatformBillingSummaryViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated, IsGodMode]

    def list(self, request):
        profiles = PlatformBillingProfile.objects.select_related("business").all()
        locked = profiles.filter(is_locked=True).count()
        no_card = profiles.filter(stripe_setup_complete=False).count()

        locked_list = [
            {
                "business_id": p.business_id,
                "business_name": getattr(p.business, "name", f"Business {p.business_id}"),
                "lock_reason": p.lock_reason,
                "locked_at": p.locked_at,
                "next_due_date": p.next_due_date,
                "grace_until": p.grace_until,
            }
            for p in profiles.filter(is_locked=True).order_by("-locked_at")[:100]
        ]

        return Response(
            {"locked_count": locked, "no_card_count": no_card, "locked_businesses": locked_list},
            status=status.HTTP_200_OK,
        )


# -------------------------
# BROADCASTS + NEWS REEL
# -------------------------
class PlatformBroadcastAPIView(APIView):
    """
    POST /api/v1/platform/broadcasts/
    {
      "title": "...",
      "body": "...",
      "send_to": "ALL" | "CUSTOMER" | "SBO" | "PM"   (optional)
    }
    """
    permission_classes = [IsAuthenticated, IsGodMode]

    def post(self, request):
        title = (request.data.get("title") or "").strip()
        body = (request.data.get("body") or "").strip()
        send_to = (request.data.get("send_to") or "ALL").strip().upper()

        if not title or not body:
            return Response({"detail": "title and body are required."}, status=status.HTTP_400_BAD_REQUEST)

        qs = User.objects.all()
        if send_to != "ALL":
            # If your User.role uses CUSTOMER/SBO/PM this matches your UI.
            qs = qs.filter(role=send_to)

        recipients = list(qs.values_list("id", flat=True))
        Notification.objects.bulk_create(
            [
                Notification(
                    recipient_id=uid,
                    actor=request.user,
                    type=Notification.TYPE_BROADCAST,
                    title=title,
                    body=body,
                    data={"send_to": send_to},
                )
                for uid in recipients
            ],
            batch_size=500,
        )
        return Response({"detail": "Broadcast sent.", "recipients": len(recipients)}, status=status.HTTP_201_CREATED)


class PlatformNewsReelAdminViewSet(ModelViewSet):
    """
    /api/v1/platform/news-reel/
    Supports multipart upload: image=<file>
    """
    serializer_class = PlatformNewsItemSerializer
    permission_classes = [IsAuthenticated, IsGodMode]
    queryset = PlatformNewsItem.objects.all().order_by("-created_at")
    parser_classes = [MultiPartParser, FormParser, JSONParser]
