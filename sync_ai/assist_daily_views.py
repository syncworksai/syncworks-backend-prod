"""Daily command center for the private SYNC Assist pilot.

This is an on-demand priority list from authorized internal records, plus owner
tasks and their local statuses. It cannot see Outlook until a separate secure
Microsoft Graph OAuth connection is established inside SyncWorks.
"""
from uuid import UUID, uuid4
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from user_accounts.models import AuditLog, Business, BusinessMember, PMProperty
from .assist_pilot_views import _pilot, _snapshot as pilot_snapshot
from .assist_discovery import _candidates

ADDED = "sync_assist.daily.added"
UPDATED = "sync_assist.daily.updated"
STATUSES = {"OPEN", "DONE", "SNOOZED"}
PRIORITIES = {"HIGH", "MEDIUM", "LOW"}
CATEGORIES = {"PROPERTY", "BUSINESS", "GROWTH", "PERSONAL"}
MAX_MANUAL = 200


def _priority(kind, source):
    if source.startswith("pm-rent-charge:") or source.startswith("overdue-invoice:"):
        return "HIGH", "PROPERTY" if source.startswith("pm-") else "BUSINESS"
    if source.startswith("pm-work-order:"):
        return "HIGH", "PROPERTY"
    if kind == "LEAD_FOLLOW_UP":
        return "MEDIUM", "BUSINESS"
    if kind == "TICKET_REVIEW":
        return "MEDIUM", "BUSINESS"
    return "LOW", "PERSONAL"


def _build(user):
    now = timezone.localtime()
    internal, scanned = _candidates(user)
    owned_ids = list(Business.objects.filter(owner=user, is_active=True, is_demo=False).values_list("id", flat=True))
    managed_count = BusinessMember.objects.filter(
        user=user, is_active=True, role__in=["OWNER", "MANAGER"],
        business__is_active=True, business__is_demo=False,
    ).exclude(business_id__in=owned_ids).count()
    owned_property_count = PMProperty.objects.filter(business_id__in=owned_ids).count()
    items = {}
    for row in internal:
        priority, category = _priority(row["kind"], row["source_key"])
        key = row["source_key"]
        items[key] = {
            "id": key, "title": row["title"], "description": row["description"],
            "priority": priority, "category": category, "source": "syncworks",
            "status": "OPEN", "action": "Review in SyncWorks",
            "updated_at": None,
        }
    events = AuditLog.objects.filter(actor=user, action__in=[ADDED, UPDATED]).order_by("id")
    for event in events:
        m = event.metadata or {}
        key = str(m.get("id", ""))
        if event.action == ADDED:
            if not key.startswith("manual:"):
                continue
            items[key] = {
                "id": key, "title": str(m.get("title", "")),
                "description": str(m.get("description", "")),
                "priority": m.get("priority", "MEDIUM"),
                "category": m.get("category", "PERSONAL"),
                "source": "manual", "status": "OPEN",
                "action": "Review task", "updated_at": event.created_at.isoformat(),
            }
        elif key in items:
            status = m.get("status")
            if status in STATUSES:
                items[key]["status"] = status
                items[key]["updated_at"] = event.created_at.isoformat()
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    visible = sorted(items.values(), key=lambda item: (item["status"] == "DONE", item["status"] == "SNOOZED", order.get(item["priority"], 2), item["title"]))[:250]
    open_items = [i for i in visible if i["status"] == "OPEN"]
    last_runs = list(AuditLog.objects.filter(
        actor=user, action="sync_assist.pilot.discovery_scan",
        metadata__run_source="scheduled",
        created_at__gte=timezone.now()-timedelta(hours=2)
    ).order_by("-id")[:2])
    return {
        "date": now.date().isoformat(), "timezone": str(now.tzinfo),
        "summary": {
            "open": len(open_items), "high_priority": sum(i["priority"] == "HIGH" for i in open_items),
            "done": sum(i["status"] == "DONE" for i in visible),
            "needs_review": len([i for i in open_items if i["source"] == "syncworks"]),
        },
        "items": visible,
        "internal_counts": scanned,
        "data_diagnostics": {
            "owned_businesses": len(owned_ids),
            "managed_businesses_not_in_owner_scan": managed_count,
            "owned_properties": owned_property_count,
            "internal_candidates_found": len(internal),
            "scan_limit": "Owner-linked active non-demo businesses, specific outstanding statuses; recent requests and tickets limited to 30 days",
            "empty_reason": (
                "No eligible owned business is linked to this account."
                if not owned_ids else
                "Owner-linked businesses exist, but no outstanding records currently match the scanner scope."
                if not internal else None
            ),
            "permission_note": "Manager-access businesses are not scanned for financial or tenant information without separate authorization.",
        },
        "connections": {
            "syncworks_internal": "live_read_only",
            "outlook_in_syncworks": "not_connected",
            "email_triage": "not_enabled",
            "automatic_morning_email": "not_enabled",
            "background_scanner": "recent_runs_verified" if len(last_runs) >= 2 else "not_verified",
        },
        "source_note": "Live internal records and manually entered to-dos only. External Outlook messages are NOT read by this SyncWorks page.",
        "can_send": False,
    }


class SyncAssistDailyView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _pilot(request.user):
            return Response({"detail": "Private pilot only."}, status=403)
        return Response(_build(request.user))

    def post(self, request):
        if not _pilot(request.user):
            return Response({"detail": "Private pilot only."}, status=403)
        title = str(request.data.get("title") or "").strip()
        desc = str(request.data.get("description") or "").strip()
        priority = str(request.data.get("priority") or "MEDIUM").upper()
        category = str(request.data.get("category") or "PERSONAL").upper()
        if not title or len(title) > 140 or len(desc) > 1000 or priority not in PRIORITIES or category not in CATEGORIES:
            return Response({"detail": "Enter a valid title, description, priority and category."}, status=400)
        if AuditLog.objects.filter(actor=request.user, action=ADDED).count() >= MAX_MANUAL:
            return Response({"detail": "Private pilot task limit reached."}, status=429)
        AuditLog.objects.create(actor=request.user, action=ADDED, metadata={
            "id": f"manual:{uuid4()}", "title": title, "description": desc,
            "priority": priority, "category": category,
        })
        return Response(_build(request.user), status=201)


class SyncAssistDailyItemView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not _pilot(request.user):
            return Response({"detail": "Private pilot only."}, status=403)
        key = str(request.data.get("id") or "")
        status = str(request.data.get("status") or "").upper()
        if not key or len(key) > 160 or status not in STATUSES:
            return Response({"detail": "Invalid task or status."}, status=400)
        # Authoritative re-read prevents writing status events for another user's work.
        current = _build(request.user)
        if not any(i["id"] == key for i in current["items"]):
            return Response({"detail": "Task not found or no longer accessible."}, status=404)
        with transaction.atomic():
            AuditLog.objects.create(actor=request.user, action=UPDATED, metadata={
                "id": key, "status": status, "external_action": False,
            })
        return Response(_build(request.user))
