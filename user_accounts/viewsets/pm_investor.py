# backend/user_accounts/viewsets/pm_investor.py
from __future__ import annotations

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet, ViewSet

from user_accounts.models import (
    Business,
    BusinessMember,
    PMProperty,
    PMInvestor,
    PMPropertyInvestor,
    PMInboxThread,
    PMInboxMessage,
    PMNotification,
)
from user_accounts.serializers.pm_investor import (
    PMInvestorSerializer,
    PMPropertyInvestorSerializer,
    PMInboxThreadSerializer,
    PMInboxMessageSerializer,
)


def _biz_id_from_request(request) -> int | None:
    raw = request.headers.get("X-Business-Id") or request.META.get("HTTP_X_BUSINESS_ID")
    try:
        return int(raw) if raw else None
    except Exception:
        return None


def _require_biz_id(request) -> int:
    biz_id = _biz_id_from_request(request)
    if not biz_id:
        raise ValidationError({"detail": "X-Business-Id header is required."})
    return biz_id


def _is_platform_admin(user) -> bool:
    return bool(getattr(user, "is_superuser", False) or getattr(user, "is_platform_admin", False))


def _role_is(user, *roles: str) -> bool:
    r = (getattr(user, "role", "") or "").upper()
    return r in {x.upper() for x in roles}


def _ensure_business_access(request, business_id: int):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        raise PermissionDenied("Authentication required.")

    if _is_platform_admin(user):
        return

    biz = Business.objects.filter(id=business_id, is_active=True).first()
    if not biz:
        raise PermissionDenied("You do not have access to this business.")

    if _role_is(user, "SBO") and getattr(biz, "owner_id", None) == getattr(user, "id", None):
        return

    is_member = BusinessMember.objects.filter(user_id=user.id, business_id=business_id, is_active=True).exists()
    if is_member:
        return

    if PMInvestor.objects.filter(business_id=business_id, user_id=user.id, is_active=True).exists():
        return

    raise PermissionDenied("You are not a member of this business.")


def _assert_property_belongs(biz_id: int, property_id: int):
    if not PMProperty.objects.filter(id=property_id, business_id=biz_id).exists():
        raise PermissionDenied("Property does not belong to this business.")


class PMInvestorViewSet(ModelViewSet):
    """
    router.register(r"pm/investors", PMInvestorViewSet, basename="pm-investors")

    PM-side management of Investors.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = PMInvestorSerializer

    def get_queryset(self):
        biz_id = _require_biz_id(self.request)
        _ensure_business_access(self.request, biz_id)
        return PMInvestor.objects.filter(business_id=biz_id).order_by("-id")

    def perform_create(self, serializer):
        biz_id = _require_biz_id(self.request)
        _ensure_business_access(self.request, biz_id)
        serializer.save(business_id=biz_id)

    def perform_update(self, serializer):
        biz_id = _require_biz_id(self.request)
        _ensure_business_access(self.request, biz_id)
        obj = self.get_object()
        if obj.business_id != biz_id:
            raise PermissionDenied("Investor not in this business.")
        serializer.save(business_id=biz_id)

    @action(detail=True, methods=["post"], url_path="assign_property")
    def assign_property(self, request, pk=None):
        biz_id = _require_biz_id(request)
        _ensure_business_access(request, biz_id)

        inv: PMInvestor = self.get_object()
        if inv.business_id != biz_id:
            raise PermissionDenied("Investor not in this business.")

        data = request.data or {}
        prop_id = data.get("property")
        try:
            prop_id = int(prop_id)
        except Exception:
            prop_id = None

        if not prop_id:
            raise ValidationError({"property": "property is required."})

        _assert_property_belongs(biz_id, prop_id)

        role = str(data.get("role") or PMPropertyInvestor.ROLE_OWNER).upper().strip()
        if role not in {PMPropertyInvestor.ROLE_OWNER, PMPropertyInvestor.ROLE_PARTNER}:
            role = PMPropertyInvestor.ROLE_OWNER

        ownership_percent = data.get("ownership_percent", None)

        link, _ = PMPropertyInvestor.objects.update_or_create(
            investor_id=inv.id,
            property_id=prop_id,
            defaults={
                "business_id": biz_id,
                "role": role,
                "ownership_percent": ownership_percent,
                "is_active": True,
            },
        )

        return Response({"ok": True, "link": PMPropertyInvestorSerializer(link).data}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="unassign_property")
    def unassign_property(self, request, pk=None):
        biz_id = _require_biz_id(request)
        _ensure_business_access(request, biz_id)

        inv: PMInvestor = self.get_object()
        data = request.data or {}
        prop_id = data.get("property")

        try:
            prop_id = int(prop_id)
        except Exception:
            prop_id = None

        if not prop_id:
            raise ValidationError({"property": "property is required."})

        PMPropertyInvestor.objects.filter(investor_id=inv.id, property_id=prop_id).update(is_active=False)
        return Response({"ok": True}, status=status.HTTP_200_OK)


class PMInboxThreadViewSet(ModelViewSet):
    """
    router.register(r"pm/inbox/threads", PMInboxThreadViewSet, basename="pm-inbox-threads")
    """
    permission_classes = [IsAuthenticated]
    serializer_class = PMInboxThreadSerializer

    def get_queryset(self):
        biz_id = _require_biz_id(self.request)
        _ensure_business_access(self.request, biz_id)

        qs = PMInboxThread.objects.filter(business_id=biz_id).select_related("investor", "property")

        # Investor users only see their own threads
        inv = PMInvestor.objects.filter(business_id=biz_id, user_id=self.request.user.id, is_active=True).first()
        if inv:
            qs = qs.filter(investor_id=inv.id)

        investor_id = self.request.query_params.get("investor")
        if investor_id and _is_platform_admin(self.request.user):
            try:
                investor_id = int(investor_id)
            except Exception:
                investor_id = None
            if investor_id:
                qs = qs.filter(investor_id=investor_id)

        prop_id = self.request.query_params.get("property")
        if prop_id:
            try:
                prop_id = int(prop_id)
            except Exception:
                prop_id = None
            if prop_id:
                qs = qs.filter(property_id=prop_id)

        return qs.order_by("-last_message_at", "-id")

    def perform_create(self, serializer):
        biz_id = _require_biz_id(self.request)
        _ensure_business_access(self.request, biz_id)

        inv = serializer.validated_data.get("investor")
        if not inv or inv.business_id != biz_id:
            raise ValidationError({"investor": "Invalid investor for this business."})

        prop = serializer.validated_data.get("property")
        if prop and prop.business_id != biz_id:
            raise ValidationError({"property": "Invalid property for this business."})

        serializer.save(business_id=biz_id, created_by=self.request.user, last_message_at=None)

    @action(detail=True, methods=["post"], url_path="mark_viewed")
    def mark_viewed(self, request, pk=None):
        biz_id = _require_biz_id(request)
        _ensure_business_access(request, biz_id)

        thread: PMInboxThread = self.get_object()
        if thread.business_id != biz_id:
            raise PermissionDenied("Thread not in this business.")

        inv = PMInvestor.objects.filter(business_id=biz_id, user_id=request.user.id, is_active=True).first()
        now = timezone.now()

        if inv:
            thread.last_viewed_by_investor_at = now
            thread.save(update_fields=["last_viewed_by_investor_at"])
        else:
            thread.last_viewed_by_pm_at = now
            thread.save(update_fields=["last_viewed_by_pm_at"])

        return Response({"ok": True})


class PMInboxMessageViewSet(ModelViewSet):
    """
    router.register(r"pm/inbox/messages", PMInboxMessageViewSet, basename="pm-inbox-messages")
    """
    permission_classes = [IsAuthenticated]
    serializer_class = PMInboxMessageSerializer

    def get_queryset(self):
        biz_id = _require_biz_id(self.request)
        _ensure_business_access(self.request, biz_id)

        qs = PMInboxMessage.objects.filter(business_id=biz_id).select_related("thread", "thread__investor", "thread__property")

        thread_id = self.request.query_params.get("thread")
        if thread_id:
            try:
                thread_id = int(thread_id)
            except Exception:
                thread_id = None
            if thread_id:
                qs = qs.filter(thread_id=thread_id)

        inv = PMInvestor.objects.filter(business_id=biz_id, user_id=self.request.user.id, is_active=True).first()
        if inv:
            qs = qs.filter(thread__investor_id=inv.id)

        return qs.order_by("created_at", "id")

    def perform_create(self, serializer):
        biz_id = _require_biz_id(self.request)
        _ensure_business_access(self.request, biz_id)

        thread = serializer.validated_data.get("thread")
        if not thread or thread.business_id != biz_id:
            raise ValidationError({"thread": "Invalid thread for this business."})

        inv = PMInvestor.objects.filter(business_id=biz_id, user_id=self.request.user.id, is_active=True).first()
        sender_role = PMInboxMessage.SENDER_INVESTOR if inv else PMInboxMessage.SENDER_PM

        with transaction.atomic():
            msg: PMInboxMessage = serializer.save(
                business_id=biz_id,
                sender_role=sender_role,
                sender_user=self.request.user,
            )

            now = timezone.now()
            thread.last_message_at = now
            thread.save(update_fields=["last_message_at"])

            # Create an Investor notification when PM sends a message
            if sender_role == PMInboxMessage.SENDER_PM:
                PMNotification.objects.create(
                    business_id=biz_id,
                    investor_id=thread.investor_id,
                    notif_type=PMNotification.TYPE_MESSAGE,
                    title="New message",
                    body=(msg.body or "")[:240],
                    thread_id=thread.id,
                    message_id=msg.id,
                )

            # Update unread tracking (optional but helpful)
            if sender_role == PMInboxMessage.SENDER_PM:
                # investor hasn't viewed this newest message yet
                pass
            else:
                # PM hasn't viewed this newest message yet
                pass


class PMInboxMetaViewSet(ViewSet):
    """
    router.register(r"pm/inbox", PMInboxMetaViewSet, basename="pm-inbox-meta")

    GET /pm/inbox/unread_count/
    """
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["get"], url_path="unread_count")
    def unread_count(self, request):
        biz_id = _require_biz_id(request)
        _ensure_business_access(request, biz_id)

        inv = PMInvestor.objects.filter(business_id=biz_id, user_id=request.user.id, is_active=True).first()

        if inv:
            # Investor: use PMNotification unread
            n = PMNotification.objects.filter(business_id=biz_id, investor_id=inv.id, read_at__isnull=True).count()
            return Response({"ok": True, "scope": "INVESTOR", "unread": int(n)})

        # PM side: unread = messages from investors since last_viewed_by_pm_at, across threads
        threads = PMInboxThread.objects.filter(business_id=biz_id)
        unread_total = 0
        for th in threads.only("id", "last_viewed_by_pm_at"):
            qs = PMInboxMessage.objects.filter(business_id=biz_id, thread_id=th.id, sender_role=PMInboxMessage.SENDER_INVESTOR)
            if th.last_viewed_by_pm_at:
                qs = qs.filter(created_at__gt=th.last_viewed_by_pm_at)
            unread_total += qs.count()

        return Response({"ok": True, "scope": "PM", "unread": int(unread_total)})


class PMInvestorPortalViewSet(ViewSet):
    """
    router.register(r"pm/investor_portal", PMInvestorPortalViewSet, basename="pm-investor-portal")

    Investor portal read-only data.
    - Investor users see their own properties
    - God mode can pass investor_id=
    """
    permission_classes = [IsAuthenticated]

    def _resolve_investor(self, request, biz_id: int) -> PMInvestor:
        inv = PMInvestor.objects.filter(business_id=biz_id, user_id=request.user.id, is_active=True).first()
        if inv:
            return inv

        investor_id = request.query_params.get("investor_id")
        if investor_id and _is_platform_admin(request.user):
            try:
                investor_id = int(investor_id)
            except Exception:
                investor_id = None
            if investor_id:
                inv2 = PMInvestor.objects.filter(id=investor_id, business_id=biz_id).first()
                if inv2:
                    return inv2

        raise PermissionDenied("Investor portal access denied.")

    @action(detail=False, methods=["get"], url_path="properties")
    def properties(self, request):
        biz_id = _require_biz_id(request)
        _ensure_business_access(request, biz_id)

        inv = self._resolve_investor(request, biz_id)

        prop_ids = list(
            PMPropertyInvestor.objects.filter(business_id=biz_id, investor_id=inv.id, is_active=True)
            .values_list("property_id", flat=True)
        )

        props = list(
            PMProperty.objects.filter(business_id=biz_id, id__in=prop_ids)
            .values("id", "name", "address", "city", "state", "zip", "status", "property_type")
        )

        return Response({"ok": True, "investor_id": inv.id, "properties": props})

    @action(detail=False, methods=["get"], url_path="rollup")
    def rollup(self, request):
        biz_id = _require_biz_id(request)
        _ensure_business_access(request, biz_id)

        inv = self._resolve_investor(request, biz_id)
        prop_count = PMPropertyInvestor.objects.filter(business_id=biz_id, investor_id=inv.id, is_active=True).count()
        thread_count = PMInboxThread.objects.filter(business_id=biz_id, investor_id=inv.id).count()
        unread_notifs = PMNotification.objects.filter(business_id=biz_id, investor_id=inv.id, read_at__isnull=True).count()

        return Response(
            {
                "ok": True,
                "investor_id": inv.id,
                "properties_count": int(prop_count),
                "threads_count": int(thread_count),
                "unread_notifications": int(unread_notifs),
            }
        )
