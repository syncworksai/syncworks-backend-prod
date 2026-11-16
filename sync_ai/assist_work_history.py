"""Owner-scoped, read-only activity history for Sync Assist pilot.

Historical evidence and failed/blocked attempts are retained as audit events.
Viewing or exporting never approves work or rewrites history.
"""
from django.core.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from uuid import UUID

from user_accounts.models import AuditLog
from .assist_pilot_views import _pilot
from .assist_workday_views import CREATED, PROGRESS, WORKED, _snapshot

EVENTS = {
    CREATED: "GOAL_CREATED",
    PROGRESS: "OWNER_PROGRESS",
    WORKED: "WORKER_RECEIPT",
}
MAX_EVENTS = 100


class SyncAssistWorkHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _pilot(request.user):
            return Response({"detail": "Private pilot only."}, status=403)
        goal_id = request.query_params.get("goal_id", "")
        if goal_id:
            try:
                goal_id = str(UUID(goal_id))
            except (ValueError, AttributeError, TypeError):
                return Response({"detail": "Invalid goal ID."}, status=400)

        events = AuditLog.objects.filter(
            actor=request.user, action__in=EVENTS,
        ).order_by("-id")
        # Actor-scoped records are filtered in the database, not from other accounts' history.
        if goal_id:
            events = events.filter(metadata__goal_id=goal_id)
        page = list(events[:MAX_EVENTS + 1])
        items = []
        for event in page[:MAX_EVENTS]:
            metadata = event.metadata or {}
            payload = {
                "event_id": event.pk,
                "timestamp": event.created_at.isoformat(),
                "kind": EVENTS[event.action],
                "goal_id": str(metadata.get("goal_id") or ""),
                "step_id": str(metadata.get("step_id") or ""),
            }
            if event.action == CREATED:
                payload.update(goal=metadata.get("goal", ""), steps=metadata.get("steps", []),
                               source_mode=metadata.get("source_mode", "INTERNAL_ONLY"))
            elif event.action == PROGRESS:
                payload.update(status=metadata.get("status"), evidence=metadata.get("evidence", ""),
                               owner_attested=metadata.get("owner_attested") is True)
            else:
                payload.update(receipt_id=metadata.get("receipt_id"), role=metadata.get("role"),
                               status=metadata.get("status"), message=metadata.get("message", ""),
                               output=metadata.get("output", []), sources=metadata.get("sources", []),
                               workflow_version=metadata.get("workflow_version"),
                               external_actions=metadata.get("external_actions", 0),
                               messages_sent=metadata.get("messages_sent", 0),
                               model_calls=metadata.get("model_calls", 0))
            items.append(payload)
        return Response({
            "events": items,
            "has_more": len(page) > MAX_EVENTS,
            "limit": MAX_EVENTS,
            "goal_id": goal_id or None,
            "notice": "Historical evidence is read-only. Previous drafts can be copied to new goals; externally executed actions cannot be undone by restoring a draft.",
        })
