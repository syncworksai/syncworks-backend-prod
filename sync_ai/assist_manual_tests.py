"""Private pilot employee manual diagnostics.

Manual tests are owner-triggered, bounded, read-only capability checks. They
record truthful receipts but do not pretend to be autonomous AI execution.
No external requests, email sends, charges, calendar writes or scraping.
"""
from datetime import timedelta
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from user_accounts.models import AuditLog, Business, Ticket, PMRentCharge, PMWorkOrder
from personal_calendar.models import PersonalCalendarEvent
from .assist_pilot_views import _pilot
from .assist_team_views import SLOTS, EXECUTABLE_ROLES
from .assist_assignment_views import _snapshot as assignments_snapshot
from .assist_growth_prospects import _snapshot as growth_snapshot
from .assist_pilot_budget import snapshot as budget_snapshot

ACTION = "sync_assist.pilot.manual_role_test"
VALID_ROLES = frozenset(slot["role"] for slot in SLOTS.values())
ROLE_NOTES = {
    "CHIEF_OF_STAFF": "Planning intake and review work. Automated delegation and outbound follow-ups are not established by this test.",
    "PROPERTY_MANAGER": "Property records can be checked internally. Section 8 correspondence and inspection scheduling require source verification and approved integrations.",
    "FINANCE_MANAGER": "Only in-app accounting record counts are checked. Actual account balances and due amounts are not verified here.",
    "SALES_MANAGER": "Owner-entered prospects can be reviewed. No contact was sent.",
    "MARKETING_MANAGER": "Owner-entered prospects can support a draft. No campaign was published.",
    "RESEARCH_ANALYST": "Existing prospect records can be reviewed. No public web research was run.",
    "EXECUTIVE_ASSISTANT": "An internal briefing handler exists, but needs previously approved specialist receipts.",
    "BUSINESS_MANAGER": "No autonomous business-management executor is connected.",
    "CUSTOMER_SERVICE": "No autonomous customer response executor is connected.",
    "PERSONAL_TRAINER": "No verified weekly workout or meal-planning executor is connected.",
}

def _summary(user, role):
    owned_business_ids = list(Business.objects.filter(owner=user, is_active=True, is_demo=False)
                              .values_list("id", flat=True)[:100])
    assigned = [item for item in assignments_snapshot(user)["assignments"]
                if item.get("role") == role]
    pending = sum(x.get("state") == "AWAITING_REVIEW" for x in assigned)
    checks = [{"label": "Role registered", "result": "PASS",
               "detail": "Fixed, private-pilot role; no tool permissions granted by the display identity."}]
    evidence = {"assignment_count": len(assigned), "pending_assignments": pending}
    checks.append({"label": "Assignment intake", "result": "PASS",
                   "detail": f"{len(assigned)} saved assignments, {pending} awaiting review."})
    supported = role in EXECUTABLE_ROLES
    checks.append({"label": "Bounded internal task handler",
                   "result": "PASS" if supported else "BLOCKED",
                   "detail": "A limited internal worker exists. This manual test did not call it."
                   if supported else "No role-specific autonomous executor is wired."})
    if role == "CHIEF_OF_STAFF":
        calendar_count = PersonalCalendarEvent.objects.filter(owner=user, status="ACTIVE",
            start_at__gte=timezone.now() - timedelta(days=1),
            start_at__lte=timezone.now() + timedelta(days=14)).count()
        evidence["upcoming_calendar_records"] = calendar_count
        checks.append({"label": "Calendar records", "result": "PASS",
                       "detail": f"{calendar_count} currently stored upcoming events; external sync freshness is unverified."})
    if role in {"PROPERTY_MANAGER", "FINANCE_MANAGER", "BUSINESS_MANAGER", "CUSTOMER_SERVICE"}:
        pending_rent = PMRentCharge.objects.filter(
            business_id__in=owned_business_ids,
            status__in=[PMRentCharge.Status.UNPAID, PMRentCharge.Status.PARTIAL],
            balance__gt=0).count()
        open_orders = PMWorkOrder.objects.filter(
            business_id__in=owned_business_ids,
            status__in=[PMWorkOrder.Status.OPEN, PMWorkOrder.Status.ON_HOLD]).count()
        evidence.update({"businesses_scoped": len(owned_business_ids),
                         "open_rent_charges": pending_rent, "open_pm_work_orders": open_orders})
        checks.append({"label": "Owned property records", "result": "PASS" if owned_business_ids else "NEEDS_SETUP",
                       "detail": f"{len(owned_business_ids)} active businesses; {pending_rent} unpaid/partial rent charges and {open_orders} open/on-hold work orders. This does not prove the Section 8 balance." if owned_business_ids else "No active non-demo business found in this account scope."})
    if role in {"SALES_MANAGER", "MARKETING_MANAGER", "RESEARCH_ANALYST"}:
        result = growth_snapshot(user)
        n = len(result["prospects"])
        evidence["owner_entered_prospects"] = n
        checks.append({"label": "Owner-entered prospect records", "result": "PASS" if n else "NEEDS_SETUP",
                       "detail": f"{n} recorded prospects, unverified for external outreach." if n else "Add sourced prospects in Growth Center to enable meaningful draft testing."})
    if role == "CHIEF_OF_STAFF":
        from .assist_outlook_views import _latest, _settings
        connected = bool(_settings() and _latest(user))
        checks.append({"label": "Outlook account connection", "result": "PASS" if connected else "NEEDS_SETUP",
                       "detail": "An Outlook token record exists; inbox access and validity were not tested."
                       if connected else "Connect Outlook in Mail Desk before email triage."})
        evidence["outlook_connection_record_present"] = connected
    checks.append({"label": "External actions", "result": "SAFE",
                   "detail": "No email, calendar event, contact, payment, application or third-party write was performed."})
    return {
        "role": role, "employee_name": next((x["name"] for x in SLOTS.values() if x["role"] == role), role),
        "mode": "READ_ONLY_DIAGNOSTIC", "worker_called": False,
        "handler_available": supported, "checks": checks, "evidence": evidence,
        "limitations": ROLE_NOTES.get(role, "No executor verified."),
        "external_actions": 0, "model_calls": 0, "estimated_model_cost_usd": "0.00",
    }

class SyncAssistManualRoleTestView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _pilot(request.user):
            return Response({"detail": "Private pilot only."}, status=403)
        latest = {}
        for item in AuditLog.objects.filter(actor=request.user, action=ACTION).order_by("-id")[:120]:
            m = item.metadata or {}
            role = m.get("role")
            if role in VALID_ROLES and role not in latest:
                latest[role] = {"tested_at": item.created_at.isoformat(),
                                "receipt": m.get("receipt")}
        return Response({"roles": [{"role": slot["role"], "name": slot["name"],
                                   "last_test": latest.get(slot["role"])}
                                  for slot in SLOTS.values()],
                         "test_type": "manual_read_only", "outbound_enabled": False,
                         "notice": "Diagnostics inspect internal records and handler availability only. A passing diagnostic is not proof the agent executed an assignment."})

    def post(self, request):
        if not _pilot(request.user):
            return Response({"detail": "Private pilot only."}, status=403)
        role = str(request.data.get("role") or "").upper().strip()
        if role not in VALID_ROLES:
            return Response({"detail": "Choose a registered employee role."}, status=400)
        # A manual check is bounded; no provider calls or external side effects.
        receipt = _summary(request.user, role)
        AuditLog.objects.create(actor=request.user, action=ACTION,
                                metadata={"role": role, "receipt": receipt})
        return Response({"receipt": receipt, "tested_at": timezone.now().isoformat(),
                         "notice": "Read-only diagnostic recorded. No AI worker executed."}, status=201)
