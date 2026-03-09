# backend/user_accounts/viewsets/pm_inbox.py
from __future__ import annotations

from typing import Any

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from user_accounts.models import (
    Business,
    BusinessMember,
    PMInboxMessage,
    PMInboxThread,
    PMInvestor,
    PMProperty,
)


# -----------------------------
# Helpers (match your PM pattern)
# -----------------------------
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

    is_member = BusinessMember.objects.filter(
        user_id=user.id,
        business_id=business_id,
        is_active=True,
    ).exists()

    if not is_member:
        raise PermissionDenied("You are not a member of this business.")


def _as_int(v: Any) -> int | None:
    try:
        if v is None or v == "":
            return None
        return int(v)
    except Exception:
        return None


# -----------------------------
# PM Inbox Threads
# -----------------------------
class PMInboxThreadViewSet(ModelViewSet):
    """
    PM-side inbox threads between PM and an Investor (owner).

    Routes (recommended):
      /api/v1/pm/inbox/threads/              (GET, POST)
      /api/v1/pm/inbox/threads/{id}/         (GET, PATCH)
      /api/v1/pm/inbox/threads/{id}/messages/ (GET)
      /api/v1/pm/inbox/threads/{id}/send/     (POST)
      /api/v1/pm/inbox/threads/{id}/close/    (POST)
      /api/v1/pm/inbox/threads/{id}/open/     (POST)
    """

    permission_classes = [IsAuthenticated]
    queryset = PMInboxThread.objects.all()

    def get_queryset(self):
        biz_id = _require_biz_id(self.request)
        _ensure_business_access(self.request, biz_id)

        qs = (
            PMInboxThread.objects.filter(business_id=biz_id)
            .select_related("investor", "property", "created_by")
            .order_by("-updated_at", "-id")
        )

        investor_id = _as_int(self.request.query_params.get("investor"))
        property_id = _as_int(self.request.query_params.get("property"))
        status_val = (self.request.query_params.get("status") or "").upper().strip()

        if investor_id:
            qs = qs.filter(investor_id=investor_id)
        if property_id:
            qs = qs.filter(property_id=property_id)
        if status_val:
            qs = qs.filter(status=status_val)

        return qs

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()

        data = []
        for th in qs[:200]:
            last_msg = (
                PMInboxMessage.objects.filter(thread_id=th.id)
                .order_by("-created_at", "-id")
                .first()
            )
            data.append(
                {
                    "id": th.id,
                    "business_id": th.business_id,
                    "investor": th.investor_id,
                    "property": th.property_id,
                    "status": th.status,
                    "subject": getattr(th, "subject", "") or "",
                    "created_at": th.created_at.isoformat() if th.created_at else None,
                    "updated_at": th.updated_at.isoformat() if th.updated_at else None,
                    "last_message": {
                        "id": last_msg.id,
                        "from_side": last_msg.from_side,
                        "body": last_msg.body,
                        "created_at": last_msg.created_at.isoformat() if last_msg.created_at else None,
                    }
                    if last_msg
                    else None,
                }
            )

        return Response({"count": qs.count(), "results": data})

    def retrieve(self, request, *args, **kwargs):
        th: PMInboxThread = self.get_object()
        biz_id = _require_biz_id(request)
        _ensure_business_access(request, biz_id)
        if th.business_id != biz_id:
            raise PermissionDenied("Thread does not belong to this business.")

        return Response(
            {
                "id": th.id,
                "business_id": th.business_id,
                "investor": th.investor_id,
                "property": th.property_id,
                "status": th.status,
                "subject": getattr(th, "subject", "") or "",
                "created_at": th.created_at.isoformat() if th.created_at else None,
                "updated_at": th.updated_at.isoformat() if th.updated_at else None,
            }
        )

    def create(self, request, *args, **kwargs):
        biz_id = _require_biz_id(request)
        _ensure_business_access(request, biz_id)

        data = request.data or {}
        investor_id = _as_int(data.get("investor"))
        property_id = _as_int(data.get("property"))
        status_val = (data.get("status") or "OPEN").upper().strip()
        subject = str(data.get("subject") or "").strip()

        if not investor_id:
            raise ValidationError({"investor": "investor is required."})
        if not property_id:
            raise ValidationError({"property": "property is required."})

        inv = PMInvestor.objects.filter(id=investor_id, business_id=biz_id, is_active=True).first()
        if not inv:
            raise ValidationError({"investor": "Invalid investor for this business."})

        prop = PMProperty.objects.filter(id=property_id, business_id=biz_id).first()
        if not prop:
            raise ValidationError({"property": "Invalid property for this business."})

        with transaction.atomic():
            # de-dupe (optional): one OPEN thread per investor/property
            existing = PMInboxThread.objects.filter(
                business_id=biz_id,
                investor_id=investor_id,
                property_id=property_id,
                status="OPEN",
            ).first()
            if existing:
                return Response(
                    {
                        "ok": True,
                        "detail": "Open thread already exists.",
                        "thread": {
                            "id": existing.id,
                            "business_id": existing.business_id,
                            "investor": existing.investor_id,
                            "property": existing.property_id,
                            "status": existing.status,
                            "subject": getattr(existing, "subject", "") or "",
                            "created_at": existing.created_at.isoformat() if existing.created_at else None,
                            "updated_at": existing.updated_at.isoformat() if existing.updated_at else None,
                        },
                    },
                    status=status.HTTP_200_OK,
                )

            th = PMInboxThread.objects.create(
                business_id=biz_id,
                investor_id=investor_id,
                property_id=property_id,
                status=status_val if status_val else "OPEN",
                subject=subject,
                created_by_id=getattr(request.user, "id", None),
            )

        return Response(
            {
                "ok": True,
                "thread": {
                    "id": th.id,
                    "business_id": th.business_id,
                    "investor": th.investor_id,
                    "property": th.property_id,
                    "status": th.status,
                    "subject": getattr(th, "subject", "") or "",
                    "created_at": th.created_at.isoformat() if th.created_at else None,
                    "updated_at": th.updated_at.isoformat() if th.updated_at else None,
                },
            },
            status=status.HTTP_201_CREATED,
        )

    def partial_update(self, request, *args, **kwargs):
        th: PMInboxThread = self.get_object()
        biz_id = _require_biz_id(request)
        _ensure_business_access(request, biz_id)
        if th.business_id != biz_id:
            raise PermissionDenied("Thread does not belong to this business.")

        data = request.data or {}
        if "status" in data:
            th.status = str(data.get("status") or "").upper().strip() or th.status
        if "subject" in data:
            th.subject = str(data.get("subject") or "").strip()

        th.updated_at = timezone.now()
        th.save(update_fields=["status", "subject", "updated_at"])

        return Response(
            {
                "ok": True,
                "thread": {
                    "id": th.id,
                    "business_id": th.business_id,
                    "investor": th.investor_id,
                    "property": th.property_id,
                    "status": th.status,
                    "subject": getattr(th, "subject", "") or "",
                    "updated_at": th.updated_at.isoformat() if th.updated_at else None,
                },
            }
        )

    @action(detail=True, methods=["get"], url_path="messages")
    def messages(self, request, pk=None):
        th: PMInboxThread = self.get_object()
        biz_id = _require_biz_id(request)
        _ensure_business_access(request, biz_id)
        if th.business_id != biz_id:
            raise PermissionDenied("Thread does not belong to this business.")

        msgs = (
            PMInboxMessage.objects.filter(thread_id=th.id)
            .select_related("sender_user")
            .order_by("created_at", "id")
        )

        return Response(
            {
                "thread_id": th.id,
                "count": msgs.count(),
                "results": [
                    {
                        "id": m.id,
                        "thread": m.thread_id,
                        "from_side": m.from_side,
                        "body": m.body,
                        "sender_user": m.sender_user_id,
                        "created_at": m.created_at.isoformat() if m.created_at else None,
                    }
                    for m in msgs[:500]
                ],
            }
        )

    @action(detail=True, methods=["post"], url_path="send")
    def send(self, request, pk=None):
        th: PMInboxThread = self.get_object()
        biz_id = _require_biz_id(request)
        _ensure_business_access(request, biz_id)
        if th.business_id != biz_id:
            raise PermissionDenied("Thread does not belong to this business.")

        body = str((request.data or {}).get("body") or "").strip()
        if not body:
            raise ValidationError({"body": "body is required."})

        with transaction.atomic():
            msg = PMInboxMessage.objects.create(
                business_id=biz_id,
                thread_id=th.id,
                from_side="PM",
                body=body,
                sender_user_id=getattr(request.user, "id", None),
            )
            th.updated_at = timezone.now()
            th.save(update_fields=["updated_at"])

        return Response(
            {
                "ok": True,
                "message": {
                    "id": msg.id,
                    "thread": msg.thread_id,
                    "from_side": msg.from_side,
                    "body": msg.body,
                    "sender_user": msg.sender_user_id,
                    "created_at": msg.created_at.isoformat() if msg.created_at else None,
                },
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="close")
    def close(self, request, pk=None):
        th: PMInboxThread = self.get_object()
        biz_id = _require_biz_id(request)
        _ensure_business_access(request, biz_id)
        if th.business_id != biz_id:
            raise PermissionDenied("Thread does not belong to this business.")

        th.status = "CLOSED"
        th.updated_at = timezone.now()
        th.save(update_fields=["status", "updated_at"])
        return Response({"ok": True, "status": th.status})

    @action(detail=True, methods=["post"], url_path="open")
    def open(self, request, pk=None):
        th: PMInboxThread = self.get_object()
        biz_id = _require_biz_id(request)
        _ensure_business_access(request, biz_id)
        if th.business_id != biz_id:
            raise PermissionDenied("Thread does not belong to this business.")

        th.status = "OPEN"
        th.updated_at = timezone.now()
        th.save(update_fields=["status", "updated_at"])
        return Response({"ok": True, "status": th.status})
