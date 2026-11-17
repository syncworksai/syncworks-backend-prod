"""Victoria's explicit, bounded multi-employee delegation template.

Creates a durable internal-only goal and opts it into the existing worker queue.
Not an LLM planner: steps are fixed, visible, and approval-gated. Nothing external
is searched, sent, published, scheduled, or charged by this endpoint.
"""
from uuid import UUID, uuid4

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import AuditLog, SyncAssistJob
from .assist_pilot_views import _pilot
from .assist_workday_views import CREATED, MAX_GOALS, _snapshot
from .assist_job_queue import enqueue_goal, serialize_job

TEMPLATES = {
    "PROSPECT_TO_OUTREACH_REVIEW": [
        ("RESEARCH_ANALYST", "Compile owner-entered prospect records with provenance for review."),
        ("SALES_MANAGER", "Prepare unsent outreach drafts using only owner-approved research."),
        ("CHIEF_OF_STAFF", "Summarize approved specialist results and present decisions to the owner."),
    ],
}


class SyncAssistDelegationView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not _pilot(request.user):
            return Response({"detail": "Private pilot only."}, status=403)
        if set(request.data.keys()) != {"template", "request_id", "allow_background_internal"}:
            return Response({"detail": "Provide only template, request_id and allow_background_internal."}, status=400)
        template = request.data.get("template")
        if not isinstance(template, str) or template not in TEMPLATES:
            return Response({"detail": "Unsupported delegation template."}, status=400)
        if request.data.get("allow_background_internal") is not True:
            return Response({"detail": "Explicit authorization for internal background execution is required."}, status=400)
        try:
            request_id = str(UUID(str(request.data.get("request_id", ""))))
        except (ValueError, TypeError, AttributeError):
            return Response({"detail": "A valid stable request_id UUID is required for safe retries."}, status=400)

        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            existing = AuditLog.objects.filter(
                actor=request.user, action=CREATED,
                metadata__delegation_request_id=request_id,
            ).first()
            if existing:
                if (existing.metadata or {}).get("delegation_template") != template:
                    return Response({"detail": "Request ID already used for another template."}, status=409)
                goal_id = str(existing.metadata["goal_id"])
                job = SyncAssistJob.objects.filter(owner=request.user, goal_id=goal_id).first()
                return Response({"goal_id": goal_id, "created": False,
                                 "job": serialize_job(job) if job else None})
            if AuditLog.objects.filter(actor=request.user, action=CREATED).count() >= MAX_GOALS:
                return Response({"detail": "Pilot goal limit reached."}, status=429)

            goal_id = str(uuid4())
            steps = [{"id": str(uuid4()), "role": role, "task": task}
                     for role, task in TEMPLATES[template]]
            AuditLog.objects.create(
                actor=request.user, action=CREATED,
                metadata={
                    "goal_id": goal_id,
                    "goal": "Victoria: review internal prospects, draft outreach, and summarize results",
                    "steps": steps, "source_mode": "INTERNAL_ONLY",
                    "public_search_query": "",
                    "delegation_template": template,
                    "delegation_request_id": request_id,
                },
            )
            job, status = enqueue_goal(request.user, goal_id)
            if job is None:
                # Prevent an orphaned goal when queue enrollment fails.
                raise RuntimeError("Delegation queue enrollment failed.")
            result = {
                "goal_id": goal_id, "created": True,
                "job": serialize_job(job), "queue_result": status,
                "steps": steps,
                "notice": "Internal-only background work; owner must approve each specialist result before the next handoff. No outbound actions.",
            }
        return Response(result, status=201)
