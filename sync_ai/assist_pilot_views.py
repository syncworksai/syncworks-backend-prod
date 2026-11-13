"""Private Sync Assist pilot task/approval control center.

Append-only AuditLog events keep the first phase migration-free, attributable and
safe. Approval is never execution. A future worker must implement separate, scoped,
idempotent actions with explicit permissions before any external side effects.
"""
from __future__ import annotations

from uuid import UUID, uuid4

from django.db import transaction
from datetime import timedelta
from django.utils import timezone
from .assist_discovery import discover_pilot_tasks
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import AuditLog

PILOT_EMAIL = "jacoblord7@outlook.com"
CREATED = "sync_assist.pilot.task_created"
APPROVED = "sync_assist.pilot.task_approved"
REJECTED = "sync_assist.pilot.task_rejected"
KINDS = {"LEAD_FOLLOW_UP", "TICKET_REVIEW", "INVOICE_REMINDER", "GENERAL"}
MAX_ITEMS = 100


def _pilot(user):
    return bool(user and user.is_authenticated and (user.email or "").strip().lower() == PILOT_EMAIL)


def _events(user):
    # The pilot log is isolated by actor, not by client-supplied identity.
    return list(AuditLog.objects.filter(actor=user, action__in=[CREATED, APPROVED, REJECTED]).order_by("id"))


def _snapshot(user):
    tasks = {}
    for item in _events(user):
        meta = item.metadata or {}
        key = str(meta.get("task_id") or "")
        if item.action == CREATED:
            tasks[key] = {
                "id": key,
                "kind": meta.get("kind", "GENERAL"),
                "title": meta.get("title", ""),
                "description": meta.get("description", ""),
                "status": "PENDING",
                "created_at": item.created_at.isoformat(),
                "decided_at": None,
            }
        elif key in tasks and tasks[key]["status"] == "PENDING":
            tasks[key]["status"] = "APPROVED" if item.action == APPROVED else "REJECTED"
            tasks[key]["decided_at"] = item.created_at.isoformat()
    ordered = list(reversed(list(tasks.values())))[:MAX_ITEMS]
    last_scan = AuditLog.objects.filter(actor=user, action="sync_assist.pilot.discovery_scan").order_by("-id").first()
    return {
        "pilot": True,
        "execution_enabled": False,
        "background_worker_enabled": False,
        "last_discovery_scan": {"at": last_scan.created_at.isoformat(), "found": last_scan.metadata.get("found", 0), "created": last_scan.metadata.get("created", 0)} if last_scan else None,
        "customer_messaging_enabled": False,
        "tasks": ordered,
        "counts": {
            "pending": sum(t["status"] == "PENDING" for t in ordered),
            "approved": sum(t["status"] == "APPROVED" for t in ordered),
            "rejected": sum(t["status"] == "REJECTED" for t in ordered),
        },
        "notice": "Approvals are recorded for review. They do not execute or send anything.",
    }


class SyncAssistPilotControlView(APIView):
    permission_classes = [IsAuthenticated]

    def _deny(self, request):
        return None if _pilot(request.user) else Response({"detail": "Private pilot only."}, status=403)

    def get(self, request):
        denied = self._deny(request)
        return denied if denied is not None else Response(_snapshot(request.user))

    def post(self, request):
        denied = self._deny(request)
        if denied is not None:
            return denied
        title = str(request.data.get("title") or "").strip()
        description = str(request.data.get("description") or "").strip()
        kind = str(request.data.get("kind") or "GENERAL").strip().upper()
        if not title or len(title) > 140 or len(description) > 2000 or kind not in KINDS:
            return Response({"detail": "Provide a title (1–140 characters), description (max 2000), and valid task kind."}, status=400)
        if AuditLog.objects.filter(actor=request.user, action=CREATED).count() >= 1000:
            return Response({"detail": "Pilot task limit reached."}, status=429)
        key = str(uuid4())
        AuditLog.objects.create(actor=request.user, action=CREATED, metadata={
            "task_id": key, "title": title, "description": description, "kind": kind,
        })
        result = _snapshot(request.user)
        result["created_task_id"] = key
        return Response(result, status=201)


class SyncAssistPilotDecisionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, task_id):
        if not _pilot(request.user):
            return Response({"detail": "Private pilot only."}, status=403)
        try:
            key = str(UUID(str(task_id)))
        except (ValueError, TypeError, AttributeError):
            return Response({"detail": "Invalid task ID."}, status=400)
        decision = str(request.data.get("decision") or "").upper()
        if decision not in {"APPROVE", "REJECT"}:
            return Response({"detail": "Decision must be APPROVE or REJECT."}, status=400)
        with transaction.atomic():
            created = AuditLog.objects.select_for_update().filter(
                actor=request.user, action=CREATED, metadata__task_id=key
            ).first()
            if not created:
                return Response({"detail": "Task not found."}, status=404)
            decided = AuditLog.objects.filter(
                actor=request.user, action__in=[APPROVED, REJECTED], metadata__task_id=key
            ).exists()
            if decided:
                return Response({"detail": "Task already decided."}, status=409)
            AuditLog.objects.create(
                actor=request.user,
                action=APPROVED if decision == "APPROVE" else REJECTED,
                metadata={"task_id": key, "execution": "NOT_ENABLED"},
            )
        return Response(_snapshot(request.user))

class SyncAssistPilotScanView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not _pilot(request.user):
            return Response({"detail": "Private pilot only."}, status=403)
        # Avoid excessive manual scans and prevent duplicate task floods.
        since = timezone.now() - timedelta(minutes=5)
        if AuditLog.objects.filter(actor=request.user, action="sync_assist.pilot.discovery_scan", created_at__gte=since).exists():
            return Response({"detail": "Last scan was within five minutes. Try again later."}, status=429)
        result = discover_pilot_tasks()
        payload = _snapshot(request.user)
        payload["scan_result"] = result
        return Response(payload)
