"""Persistent, per-user AI workforce beta controls.

No autonomous task execution, money movement, connector tokens or external messaging.
AuditLog-backed beta avoids introducing an unreviewed production migration.
"""
from __future__ import annotations

from uuid import uuid4
from django.db import transaction
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from user_accounts.models import AuditLog
from .employee_catalog import CATALOG

ACTIVATE = "sync_assist.employee.activate"
DEACTIVATE = "sync_assist.employee.deactivate"
ASSIGN = "sync_assist.employee.assignment_created"
MAX_ASSIGNMENTS = 200
MAX_TITLE = 140
MAX_INSTRUCTIONS = 2500


def _enabled(user):
    # All authenticated accounts may trial employee activation without checkout.
    events = AuditLog.objects.filter(actor=user, action__in=[ACTIVATE, DEACTIVATE]).order_by("id")
    enabled = {"chief_of_staff"}
    for event in events:
        role = (event.metadata or {}).get("employee_id")
        if role not in CATALOG:
            continue
        if event.action == ACTIVATE:
            enabled.add(role)
        elif role != "chief_of_staff":
            enabled.discard(role)
    return enabled


def _assignments(user):
    rows = AuditLog.objects.filter(actor=user, action=ASSIGN).order_by("-id")[:MAX_ASSIGNMENTS]
    return [
        {
            "id": (r.metadata or {}).get("id"),
            "employee_id": (r.metadata or {}).get("employee_id"),
            "title": (r.metadata or {}).get("title"),
            "instructions": (r.metadata or {}).get("instructions"),
            "status": "QUEUED_FOR_REVIEW",
            "execution_enabled": False,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


def _roster(user):
    active = _enabled(user)
    return {
        "beta": True,
        "billing_enabled": False,
        "execution_enabled": False,
        "employees": [
            {**template, "active": role in active, "status": "ACTIVE" if role in active else "AVAILABLE"}
            for role, template in CATALOG.items()
        ],
        "assignment_count": AuditLog.objects.filter(actor=user, action=ASSIGN).count(),
        "notice": "Assignments are stored for review; an employee will not run, browse, email or modify connected accounts yet.",
    }


class AIEmployeeRosterView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(_roster(request.user))


class AIEmployeeActivationView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, employee_id):
        if employee_id not in CATALOG:
            return Response({"detail": "Unknown employee."}, status=404)
        action = str(request.data.get("action") or "").upper()
        if action not in {"ACTIVATE", "DEACTIVATE"}:
            return Response({"detail": "action must be ACTIVATE or DEACTIVATE."}, status=400)
        if employee_id == "chief_of_staff" and action == "DEACTIVATE":
            return Response({"detail": "Chief of Staff is included with Sync Assist."}, status=400)
        with transaction.atomic():
            # Lock the account, rather than a nonexistent roster row, to serialize changes.
            from django.contrib.auth import get_user_model
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            currently_active = employee_id in _enabled(request.user)
            requested_active = action == "ACTIVATE"
            if currently_active != requested_active:
                AuditLog.objects.create(
                    actor=request.user,
                    action=ACTIVATE if requested_active else DEACTIVATE,
                    metadata={"employee_id": employee_id, "price_cents": 0, "billing": False},
                )
        return Response(_roster(request.user))


class AIEmployeeAssignmentsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"assignments": _assignments(request.user), "execution_enabled": False})

    def post(self, request):
        role = str(request.data.get("employee_id") or "").strip()
        title = request.data.get("title")
        instructions = request.data.get("instructions")
        if role not in CATALOG:
            return Response({"detail": "Choose a valid employee."}, status=400)
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= MAX_TITLE:
            return Response({"detail": "Title must be 1-140 characters."}, status=400)
        if not isinstance(instructions, str) or not 1 <= len(instructions.strip()) <= MAX_INSTRUCTIONS:
            return Response({"detail": "Instructions must be 1-2500 characters."}, status=400)
        if role not in _enabled(request.user):
            return Response({"detail": "Activate this employee before assigning work."}, status=403)
        with transaction.atomic():
            from django.contrib.auth import get_user_model
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            if AuditLog.objects.filter(actor=request.user, action=ASSIGN).count() >= MAX_ASSIGNMENTS:
                return Response({"detail": "Beta assignment limit reached."}, status=429)
            identifier = str(uuid4())
            AuditLog.objects.create(actor=request.user, action=ASSIGN, metadata={
                "id": identifier, "employee_id": role,
                "title": title.strip(), "instructions": instructions.strip(),
                "execution": "NOT_ENABLED",
            })
        return Response({
            "id": identifier, "employee_id": role,
            "status": "QUEUED_FOR_REVIEW", "execution_enabled": False,
            "notice": "Assignment saved; no automated work has been performed.",
        }, status=201)
