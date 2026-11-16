"""Auditable private-pilot goals and human-verified delegation.

This module intentionally performs no external side effects or LLM execution.
A progress report only reflects recorded human actions; an AI worker must have
a separate permissioned execution path and verifiable tool receipts.
"""
from __future__ import annotations

from uuid import UUID, uuid4

from django.db import transaction
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import AuditLog
from .assist_pilot_views import _pilot

CREATED = "sync_assist.workday.goal_created"
PROGRESS = "sync_assist.workday.progress_recorded"
ROLES = {
    "CHIEF_OF_STAFF", "EXECUTIVE_ASSISTANT", "RESEARCH_ANALYST",
    "SALES_MANAGER", "MARKETING_MANAGER", "BUSINESS_MANAGER",
    "FINANCE_MANAGER", "PROPERTY_MANAGER", "CUSTOMER_SERVICE",
    "PERSONAL_TRAINER",
}
STATES = {"PLANNED", "IN_PROGRESS", "BLOCKED", "AWAITING_APPROVAL", "COMPLETED"}
MAX_GOALS = 100
MAX_STEPS = 8


def _snapshot(user):
    goals = {}
    events = AuditLog.objects.filter(actor=user, action__in=[CREATED, PROGRESS]).order_by("id")
    for event in events:
        data = event.metadata or {}
        identifier = str(data.get("goal_id") or "")
        if event.action == CREATED:
            if not identifier or identifier in goals:
                continue
            steps = data.get("steps") or []
            goals[identifier] = {
                "id": identifier,
                "goal": data.get("goal", ""),
                "status": "PLANNED",
                "created_at": event.created_at.isoformat(),
                "updated_at": event.created_at.isoformat(),
                "steps": [
                    {"id": step["id"], "role": step["role"], "task": step["task"],
                     "status": "PLANNED", "evidence": "", "verified_by": None}
                    for step in steps if isinstance(step, dict) and all(k in step for k in ("id", "role", "task"))
                ],
            }
        elif identifier in goals:
            target = next((step for step in goals[identifier]["steps"] if step["id"] == data.get("step_id")), None)
            if target is None or data.get("status") not in STATES:
                continue
            target["status"] = data["status"]
            target["evidence"] = data.get("evidence", "")
            target["verified_by"] = "owner" if data["status"] == "COMPLETED" else None
            goals[identifier]["updated_at"] = event.created_at.isoformat()
    for goal in goals.values():
        statuses = [step["status"] for step in goal["steps"]]
        if statuses and all(state == "COMPLETED" for state in statuses):
            goal["status"] = "COMPLETED"
        elif "BLOCKED" in statuses:
            goal["status"] = "BLOCKED"
        elif "AWAITING_APPROVAL" in statuses:
            goal["status"] = "AWAITING_APPROVAL"
        elif any(state != "PLANNED" for state in statuses):
            goal["status"] = "IN_PROGRESS"
    ordered = list(reversed(list(goals.values())))[:MAX_GOALS]
    return {
        "goals": ordered,
        "counts": {state.lower(): sum(g["status"] == state for g in ordered) for state in STATES},
        "execution_enabled": False,
        "completion_policy": "Owner attestation with evidence; not autonomous tool verification.",
        "notice": "These are owner-defined assignments. No employee has performed an external action through this endpoint.",
    }


class SyncAssistWorkdayView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _pilot(request.user):
            return Response({"detail": "Private pilot only."}, status=403)
        return Response(_snapshot(request.user))

    def post(self, request):
        if not _pilot(request.user):
            return Response({"detail": "Private pilot only."}, status=403)
        goal = request.data.get("goal")
        steps = request.data.get("steps")
        if not isinstance(goal, str) or not goal.strip() or len(goal.strip()) > 500:
            return Response({"detail": "Goal must be 1–500 characters."}, status=400)
        if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
            return Response({"detail": "Provide 1–8 employee assignments."}, status=400)
        prepared = []
        for step in steps:
            if not isinstance(step, dict):
                return Response({"detail": "Each assignment must be an object."}, status=400)
            role, task = step.get("role"), step.get("task")
            if role not in ROLES or not isinstance(task, str) or not task.strip() or len(task.strip()) > 500:
                return Response({"detail": "Each assignment needs a supported role and task (1–500 characters)."}, status=400)
            prepared.append({"id": str(uuid4()), "role": role, "task": task.strip()})
        with transaction.atomic():
            # Lock the account row so concurrent submissions cannot bypass limits.
            from django.contrib.auth import get_user_model
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            if AuditLog.objects.filter(actor=request.user, action=CREATED).count() >= MAX_GOALS:
                return Response({"detail": "Pilot goal limit reached."}, status=429)
            identifier = str(uuid4())
            AuditLog.objects.create(
                actor=request.user, action=CREATED,
                metadata={"goal_id": identifier, "goal": goal.strip(), "steps": prepared},
            )
        response = _snapshot(request.user)
        response["created_goal_id"] = identifier
        return Response(response, status=201)


class SyncAssistWorkdayProgressView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, goal_id, step_id):
        if not _pilot(request.user):
            return Response({"detail": "Private pilot only."}, status=403)
        try:
            goal_id, step_id = str(UUID(str(goal_id))), str(UUID(str(step_id)))
        except (TypeError, ValueError, AttributeError):
            return Response({"detail": "Invalid goal or assignment ID."}, status=400)
        status = request.data.get("status")
        evidence = request.data.get("evidence", "")
        attested = request.data.get("owner_attested") is True
        if status not in STATES or not isinstance(evidence, str) or len(evidence) > 2000:
            return Response({"detail": "Invalid status or evidence."}, status=400)
        if status == "COMPLETED" and (not attested or len(evidence.strip()) < 15):
            return Response({"detail": "Completion requires owner attestation and at least 15 characters of evidence."}, status=400)
        with transaction.atomic():
            from django.contrib.auth import get_user_model
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            snapshot = _snapshot(request.user)
            goal = next((item for item in snapshot["goals"] if item["id"] == goal_id), None)
            step = next((item for item in goal["steps"] if item["id"] == step_id), None) if goal else None
            if step is None:
                return Response({"detail": "Goal or assignment not found."}, status=404)
            if step["status"] == "COMPLETED":
                return Response({"detail": "Completed assignment is immutable."}, status=409)
            AuditLog.objects.create(
                actor=request.user, action=PROGRESS,
                metadata={"goal_id": goal_id, "step_id": step_id, "status": status,
                          "evidence": evidence.strip(), "owner_attested": attested},
            )
        return Response(_snapshot(request.user))
