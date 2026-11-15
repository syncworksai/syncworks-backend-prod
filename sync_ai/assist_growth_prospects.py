"""Private, no-send Sync Assist growth prospect queue.

Owner-entered public business details become reviewable outreach drafts. This
does not scrape social networks, look up personal identities, or send messages.
"""
from urllib.parse import urlparse
from uuid import uuid4, UUID

from django.db import transaction
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import AuditLog
from .assist_pilot_views import _pilot

CREATE = "sync_assist.growth.prospect_created"
UPDATE = "sync_assist.growth.prospect_updated"
NICHES = {
    "home_services": "home-service companies managing calls, schedules and jobs",
    "property_management": "property managers coordinating tenants, maintenance and rent",
    "independent_services": "independent service businesses juggling customer requests and invoices",
}
STAGES = {"RESEARCH", "READY_FOR_REVIEW", "CONTACTED_MANUALLY", "RESPONDED", "DEMO_BOOKED", "TRIAL", "CLOSED_WON", "NOT_INTERESTED", "DO_NOT_CONTACT"}
CHANNELS = {"EMAIL", "MESSENGER", "PHONE", "OTHER"}


def _draft(company, niche, observation):
    if niche == "property_management":
        problem = "organizing maintenance requests, tenant communications and property workflows"
    elif niche == "home_services":
        problem = "keeping customer requests, scheduling, job tickets and invoices together"
    else:
        problem = "simplifying follow-ups, appointments and customer work"
    # Deliberately avoid claims that the prospect has a problem unless verified.
    context = f" I noticed {observation.strip()}." if observation.strip() else ""
    return (
        f"Hi {company} team, I'm reaching out from SyncWorks.{context} "
        f"We're building a service platform focused on {problem}. "
        "Would you be open to a short demo to see whether it's useful for your business? "
        "No pressure if it's not a fit."
    )[:1200]


def _snapshot(user):
    entries = AuditLog.objects.filter(actor=user, action__in=[CREATE, UPDATE]).order_by("id")
    items = {}
    for entry in entries:
        m = entry.metadata or {}
        pid = str(m.get("prospect_id", ""))
        if entry.action == CREATE and pid:
            items[pid] = {k: m.get(k) for k in ("prospect_id", "company", "niche", "website", "public_contact", "observation", "channel", "draft", "stage")}
            items[pid]["created_at"] = entry.created_at.isoformat()
        elif pid in items and entry.action == UPDATE:
            items[pid]["stage"] = m.get("stage", items[pid]["stage"])
            items[pid]["updated_at"] = entry.created_at.isoformat()
    output = list(reversed(list(items.values())))[:100]
    return {
        "pilot": True, "prospects": output,
        "counts": {stage: sum(item["stage"] == stage for item in output) for stage in sorted(STAGES)},
        "outbound_automation_enabled": False,
        "platform_connections_required": False,
        "notice": "Drafts are for owner review. No direct messages, emails, scraping, or external contact actions run from this page.",
    }


class SyncAssistGrowthProspectsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _pilot(request.user):
            return Response({"detail": "Private pilot only."}, status=403)
        return Response(_snapshot(request.user))

    def post(self, request):
        if not _pilot(request.user):
            return Response({"detail": "Private pilot only."}, status=403)
        company = str(request.data.get("company") or "").strip()
        niche = str(request.data.get("niche") or "").strip()
        website = str(request.data.get("website") or "").strip()
        public_contact = str(request.data.get("public_contact") or "").strip()
        observation = str(request.data.get("observation") or "").strip()
        channel = str(request.data.get("channel") or "EMAIL").strip().upper()
        if not company or len(company) > 140 or niche not in NICHES or channel not in CHANNELS or len(public_contact) > 220 or len(observation) > 350 or len(website) > 300:
            return Response({"detail": "Provide a valid company, niche, channel, and short public notes."}, status=400)
        if website:
            url = urlparse(website)
            if url.scheme not in {"https", "http"} or not url.netloc or url.username or url.password:
                return Response({"detail": "Website must be a public http(s) URL."}, status=400)
        # Avoid accidental bulk ingestion; no automated imports.
        if AuditLog.objects.filter(actor=request.user, action=CREATE).count() >= 250:
            return Response({"detail": "Pilot limit reached."}, status=429)
        # Protect against duplicate company entries irrespective of case.
        existing = AuditLog.objects.filter(actor=request.user, action=CREATE).values_list("metadata__company", flat=True)
        if any(str(name or "").strip().casefold() == company.casefold() for name in existing):
            return Response({"detail": "A prospect with this company name already exists."}, status=409)
        prospect_id = str(uuid4())
        AuditLog.objects.create(actor=request.user, action=CREATE, metadata={
            "prospect_id": prospect_id, "company": company, "niche": niche,
            "website": website, "public_contact": public_contact,
            "observation": observation, "channel": channel,
            "draft": _draft(company, niche, observation),
            "stage": "READY_FOR_REVIEW",
            "sent": False,
        })
        payload = _snapshot(request.user)
        payload["created_prospect_id"] = prospect_id
        return Response(payload, status=201)


class SyncAssistGrowthProspectStageView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, prospect_id):
        if not _pilot(request.user):
            return Response({"detail": "Private pilot only."}, status=403)
        try:
            pid = str(UUID(str(prospect_id)))
        except (TypeError, ValueError, AttributeError):
            return Response({"detail": "Invalid prospect ID."}, status=400)
        stage = str(request.data.get("stage") or "").strip().upper()
        if stage not in STAGES:
            return Response({"detail": "Invalid stage."}, status=400)
        with transaction.atomic():
            created = AuditLog.objects.select_for_update().filter(actor=request.user, action=CREATE, metadata__prospect_id=pid).first()
            if not created:
                return Response({"detail": "Prospect not found."}, status=404)
            AuditLog.objects.create(actor=request.user, action=UPDATE, metadata={"prospect_id": pid, "stage": stage, "external_action": False})
        return Response(_snapshot(request.user))
