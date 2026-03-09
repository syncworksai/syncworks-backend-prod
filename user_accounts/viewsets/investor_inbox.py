# backend/user_accounts/viewsets/investor_inbox.py
from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from user_accounts.models import PMInboxMessage, PMInboxThread, PMInvestor


class InvestorInboxThreadViewSet(ViewSet):
    """
    Investor-side inbox:
      GET  /api/v1/investor/inbox/threads/
      GET  /api/v1/investor/inbox/threads/{id}/messages/
      POST /api/v1/investor/inbox/threads/{id}/send/
    """

    permission_classes = [IsAuthenticated]

    def _get_investor(self, request) -> PMInvestor:
        inv = PMInvestor.objects.filter(user_id=request.user.id, is_active=True).first()
        if not inv:
            raise PermissionDenied("Investor profile not linked. Claim your investor profile first.")
        return inv

    def list(self, request):
        inv = self._get_investor(request)

        qs = (
            PMInboxThread.objects.filter(investor_id=inv.id)
            .select_related("property", "created_by")
            .order_by("-updated_at", "-id")
        )

        results = []
        for th in qs[:200]:
            last_msg = (
                PMInboxMessage.objects.filter(thread_id=th.id)
                .order_by("-created_at", "-id")
                .first()
            )
            results.append(
                {
                    "id": th.id,
                    "business_id": th.business_id,
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

        return Response({"count": qs.count(), "results": results})

    @action(detail=True, methods=["get"], url_path="messages")
    def messages(self, request, pk=None):
        inv = self._get_investor(request)

        th = PMInboxThread.objects.filter(id=pk, investor_id=inv.id).first()
        if not th:
            raise PermissionDenied("Thread not found.")

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
        inv = self._get_investor(request)

        th = PMInboxThread.objects.filter(id=pk, investor_id=inv.id).first()
        if not th:
            raise PermissionDenied("Thread not found.")

        if str(th.status or "").upper() == "CLOSED":
            raise ValidationError({"detail": "Thread is closed."})

        body = str((request.data or {}).get("body") or "").strip()
        if not body:
            raise ValidationError({"body": "body is required."})

        with transaction.atomic():
            msg = PMInboxMessage.objects.create(
                business_id=th.business_id,
                thread_id=th.id,
                from_side="INVESTOR",
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
                    "created_at": msg.created_at.isoformat() if msg.created_at else None,
                },
            },
            status=status.HTTP_201_CREATED,
        )
