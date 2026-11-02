"""Permission-scoped, review-first intake for SyncWorks' three marketplace flows.

This module deliberately does not send messages, dispatch providers, change
schedules, or call a model. A manager must explicitly confirm creation of a
property-management work order.
"""
from __future__ import annotations

import re

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from pm_workspace.models import PMProperty, PMWorkspace
from pm_workspace.workorder_models import PMWorkOrder
from user_accounts.models import AuditLog

from .context import resolve_workspace


class WorkflowIntakeThrottle(UserRateThrottle):
    scope = "sync_ai"

    def get_rate(self):
        return "30/hour"


WORKFLOWS = {
    "maintenance": {
        "label": "Property maintenance",
        "route": "/pm/work-orders",
        "questions": [
            "Which property and unit need service?",
            "Is the issue active, and is there any immediate danger?",
            "Are there photos, access instructions, or a preferred time?",
        ],
    },
    "service_booking": {
        "label": "Service booking",
        "route": "/customer/new-request",
        "questions": [
            "What service do you need and where?",
            "What date or time works for you?",
            "Do you have any photos or special instructions?",
        ],
    },
    "sales_lead": {
        "label": "Sales lead",
        "route": "/sbo/leads",
        "questions": [
            "Who is interested, and how may the business contact them?",
            "What product or service are they interested in?",
            "What is their preferred next step?",
        ],
    },
}


def _classify(text):
    message = text.lower()
    if any(phrase in message for phrase in ("tenant", "rental", "work order", "maintenance", "landlord")):
        return "maintenance"
    if any(phrase in message for phrase in ("prospect", "lead", "consultation", "education course", "follow up", "training program")):
        return "sales_lead"
    return "service_booking"


def _risk(text):
    value = text.lower()
    if re.search(r"\b(gas leak|smell gas|fire|smoke|sparking|exposed live wire|flooding|burst pipe)\b", value):
        return "EMERGENCY", "Potential immediate danger. Follow your emergency policy and contact emergency services or the utility when appropriate."
    if re.search(r"\b(leaking|active leak|water damage|no heat|no ac|sewage|electrical hazard)\b", value):
        return "HIGH", "Prompt human review is recommended. Urgency is a suggestion, not a confirmed diagnosis."
    return "ROUTINE", ""


def _category(text):
    value = text.lower()
    if any(term in value for term in ("leak", "sink", "pipe", "toilet", "drain", "faucet", "water")):
        return "PLUMBING"
    if any(term in value for term in ("electric", "outlet", "gfci", "wire", "light", "spark")):
        return "ELECTRICAL"
    if any(term in value for term in ("ac", "air condition", "heating", "hvac", "furnace")):
        return "HVAC"
    return "GENERAL"


def _portfolio(request):
    raw_id = (
        request.headers.get("X-PM-Workspace-ID")
        or request.data.get("pm_workspace_id")
    )
    allowed = PMWorkspace.objects.filter(owner=request.user, is_active=True)
    if raw_id:
        portfolio = allowed.filter(pk=raw_id).first() if str(raw_id).isdigit() else None
    else:
        portfolio = allowed.order_by("id").first()
    if portfolio is None:
        raise PermissionError("Select a Property Management portfolio you own.")
    return portfolio


def _scope(request):
    workspace = str(request.data.get("workspace") or "personal").strip().lower()
    if workspace == "pm":
        portfolio = _portfolio(request)
        return workspace, portfolio
    business_id = request.headers.get("X-Business-ID") or request.data.get("business_id")
    resolve_workspace(
        user=request.user,
        workspace=workspace,
        business_id=str(business_id) if business_id else None,
    )
    return workspace, None


def _error(error):
    if isinstance(error, PermissionError):
        return Response({"detail": str(error)}, status=status.HTTP_403_FORBIDDEN)
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


class SyncWorkflowIntakePreviewView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [WorkflowIntakeThrottle]

    def post(self, request):
        description = str(request.data.get("description") or "").strip()
        if len(description) < 10 or len(description) > 3000:
            return Response(
                {"detail": "Describe the request in 10 to 3000 characters."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            workspace, portfolio = _scope(request)
        except (ValueError, PermissionError) as exc:
            return _error(exc)

        requested_type = str(request.data.get("workflow_type") or "auto").strip().lower()
        workflow_type = _classify(description) if requested_type == "auto" else requested_type
        if workflow_type not in WORKFLOWS:
            return Response({"detail": "Unsupported workflow type."}, status=status.HTTP_400_BAD_REQUEST)
        if workflow_type == "sales_lead" and workspace != "business":
            return Response({"detail": "Select a Business workspace to prepare sales leads."}, status=status.HTTP_403_FORBIDDEN)

        info = WORKFLOWS[workflow_type]
        priority, safety_alert = _risk(description) if workflow_type == "maintenance" else ("ROUTINE", "")
        properties = []
        if portfolio and workflow_type == "maintenance":
            properties = list(
                PMProperty.objects.filter(workspace=portfolio)
                .order_by("name", "id")
                .values("id", "name", "address")[:100]
            )

        AuditLog.objects.create(
            actor=request.user,
            action="sync_ai.workflow_intake_previewed",
            metadata={
                "workspace": workspace,
                "workflow_type": workflow_type,
                "pm_workspace_id": str(portfolio.id) if portfolio else "",
                "description_length": len(description),
                "executed": False,
            },
        )
        return Response({
            "workflow_type": workflow_type,
            "label": info["label"],
            "workspace": workspace,
            "priority_suggestion": priority,
            "category_suggestion": _category(description) if workflow_type == "maintenance" else "",
            "safety_alert": safety_alert,
            "questions": info["questions"],
            "route": "/customer/new-request" if workflow_type == "maintenance" and workspace != "pm" else info["route"],
            "pm_workspace_id": portfolio.id if portfolio else None,
            "properties": properties,
            "can_create_pm_work_order": bool(portfolio and properties and workflow_type == "maintenance"),
            "status": "review_required",
            "executed": False,
        })


class SyncWorkflowPMWorkOrderCreateView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [WorkflowIntakeThrottle]

    @transaction.atomic
    def post(self, request):
        if request.data.get("confirmed") is not True:
            return Response({"detail": "Confirm the property and final description before creating a work order."}, status=400)
        if str(request.data.get("workspace") or "").strip().lower() != "pm":
            return Response({"detail": "A PM workspace is required."}, status=403)
        try:
            portfolio = _portfolio(request)
        except PermissionError as exc:
            return _error(exc)

        property_id = str(request.data.get("property_id") or "")
        prop = PMProperty.objects.filter(
            workspace=portfolio,
            pk=property_id,
        ).first() if property_id.isdigit() else None
        if prop is None:
            return Response({"detail": "Select a property within your active PM portfolio."}, status=400)

        title = str(request.data.get("title") or "").strip()
        description = str(request.data.get("description") or "").strip()
        if not 5 <= len(title) <= 180 or not 10 <= len(description) <= 3000:
            return Response({"detail": "Title must be 5-180 characters and description 10-3000 characters."}, status=400)

        priority, _ = _risk(description)
        category = _category(description)
        order = PMWorkOrder.objects.create(
            workspace=portfolio,
            property=prop,
            created_by=request.user,
            source=PMWorkOrder.Source.OFFICE,
            title=title,
            description=description,
            category=category,
            priority=priority,
            status=PMWorkOrder.Status.TRIAGE,
            dispatch_mode=PMWorkOrder.Dispatch.UNASSIGNED,
            active_leak=bool(re.search(r"\b(leaking|active leak|burst pipe)\b", description.lower())),
            electrical_hazard=bool(re.search(r"\b(sparking|exposed live wire|electrical hazard)\b", description.lower())),
        )
        AuditLog.objects.create(
            actor=request.user,
            action="sync_ai.pm_work_order_created",
            metadata={
                "pm_workspace_id": str(portfolio.id),
                "property_id": str(prop.id),
                "work_order_id": str(order.id),
                "priority": priority,
                "confirmed": True,
                "marketplace_published": False,
            },
        )
        return Response({
            "id": order.id,
            "status": order.status,
            "priority": order.priority,
            "property_id": prop.id,
            "marketplace_published": False,
            "executed": True,
            "route": f"/pm/work-orders?property={prop.id}",
        }, status=status.HTTP_201_CREATED)
