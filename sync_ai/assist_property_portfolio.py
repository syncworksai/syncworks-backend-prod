"""Read-only portfolio linking and executive property correspondence briefing.

No Outlook emails are moved or sent, no ledger entry is created, and no
correspondence is auto-attached by this module.
"""
from collections import Counter, defaultdict
from datetime import timedelta
from uuid import uuid4

from django.db import transaction
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from pm_workspace.models import PMProperty, PMProject, PMTenant
from user_accounts.models import AuditLog
from .assist_pilot_views import _pilot
from .assist_property_history import (
    PROFILE, REPORT, MAX_PROFILES, profiles, mailbox, property_for_user, correspondence_intelligence
)


def owned_properties(user):
    return PMProperty.objects.filter(
        workspace__owner=user, workspace__is_active=True
    ).order_by("id")


def property_terms(prop):
    # Unambiguous identifiers first. General financial words are excluded:
    # rent/lease/payment alone often yield unrelated bank/promotional mail.
    terms = []
    for candidate in [prop.address, prop.name]:
        candidate = str(candidate or "").strip().lower()
        if len(candidate) >= 5 and candidate not in terms:
            terms.append(candidate)
    return terms[:15]


class PropertyLinkAllView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, account_id):
        if not mailbox(request, account_id):
            return Response({"detail": "Property mailbox not connected or access denied."}, status=403)
        owned = list(owned_properties(request.user)[:MAX_PROFILES + 1])
        linked = {str(p.get("pm_property_id")) for p in profiles(request.user, str(account_id))
                  if p.get("pm_property_id")}
        return Response({
            "total": len(owned),
            "linked": sum(str(p.id) in linked for p in owned),
            "unlinked": sum(str(p.id) not in linked for p in owned),
            "limit": MAX_PROFILES,
            "over_limit": len(owned) > MAX_PROFILES,
            "mode": "LINK_ONLY_NO_EMAIL_CHANGES",
        })

    def post(self, request, account_id):
        if not mailbox(request, account_id):
            return Response({"detail": "Property mailbox not connected or access denied."}, status=403)
        owned = list(owned_properties(request.user)[:MAX_PROFILES + 1])
        if len(owned) > MAX_PROFILES:
            return Response({"detail": "Portfolio exceeds the current per-mailbox linking limit."}, status=400)
        current = profiles(request.user, str(account_id))
        used = {str(p.get("pm_property_id")) for p in current if p.get("pm_property_id")}
        unmatched = [p for p in current if not p.get("pm_property_id")]
        created = []
        skipped = []
        # Preserve existing manually maintained search profiles and contacts.
        # An existing unlinked profile is NOT guessed from a fuzzy name match.
        with transaction.atomic():
            for prop in owned:
                if str(prop.id) in used:
                    skipped.append(prop.id)
                    continue
                terms = property_terms(prop)
                if not terms:
                    skipped.append(prop.id)
                    continue
                meta = {
                    "profile_id": str(uuid4()), "mailbox_id": str(account_id),
                    "pm_property_id": prop.id, "property_address": prop.address,
                    "name": prop.name, "terms": terms, "contacts": [],
                    "source": "pm_link_all",
                }
                AuditLog.objects.create(actor=request.user, action=PROFILE, metadata=meta)
                created.append({"pm_property_id": prop.id, "profile_id": meta["profile_id"], "name": prop.name})
        return Response({
            "created": created, "already_linked_or_skipped": skipped,
            "unlinked_manual_profiles": len(unmatched),
            "total": len(owned), "linked": len(created) + len(skipped),
            "message": "Portfolio properties linked for read-only search; existing manual searches preserved.",
            "outlook_modified": False, "evidence_attached": False,
            "tenant_messaging_enabled": False,
        })


class PropertyPortfolioBriefView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _pilot(request.user):
            return Response({"detail": "Not authorized."}, status=403)
        owned = list(owned_properties(request.user)[:MAX_PROFILES + 1])
        ids = {p.id for p in owned}
        today = timezone.localdate()
        project_counts = Counter()
        overdue_projects = Counter()
        leases_ending = defaultdict(list)
        for task in PMProject.objects.filter(property_id__in=ids).exclude(
                status__in=["COMPLETED", "ARCHIVED"]):
            project_counts[task.property_id] += 1
            if task.target_date and task.target_date < today:
                overdue_projects[task.property_id] += 1
        for resident in PMTenant.objects.filter(property_id__in=ids).exclude(status="INACTIVE"):
            if resident.lease_end and today <= resident.lease_end <= today + timedelta(days=60):
                leases_ending[resident.property_id].append(resident.lease_end.isoformat())
        reports = {}
        events = AuditLog.objects.filter(actor=request.user, action=REPORT).order_by("-id").iterator()
        for event in events:
            row = event.metadata or {}
            prop_id = row.get("pm_property_id")
            if prop_id in ids:
                reports.setdefault(prop_id, []).append(row)
        properties = []
        totals = Counter()
        for prop in owned:
            history = reports.get(prop.id, [])
            intelligence = correspondence_intelligence(history)
            items = list(reversed(intelligence["timeline"]))
            counts = Counter(str(item.get("category") or "REVIEW") for item in items)
            totals.update(counts)
            properties.append({
                "id": prop.id, "name": prop.name,
                "status": prop.status, "correspondence_count": len(items),
                "latest_correspondence_at": items[0].get("received_at") if items else None,
                "categories": dict(counts),
                "correspondence_issues": [{k: v for k, v in issue.items() if k != "evidence"} for issue in intelligence["issues"]],
                "operations": {
                    "open_projects": project_counts[prop.id],
                    "overdue_projects": overdue_projects[prop.id],
                    "recorded_leases_ending_within_60_days": len(leases_ending[prop.id]),
                    "lease_end_dates": sorted(leases_ending[prop.id])[:10],
                    "requires_financial_reconciliation": True,
                },
                "requires_review": any(r.get("status") == "CORRESPONDENCE_REVIEW_ONLY" for r in history),
                "detail_url": f"/pm/properties/{prop.id}?tab=correspondence",
            })
        return Response({
            "generated_at": timezone.now().isoformat(),
            "properties": properties, "portfolio_property_count": len(owned),
            "reviewed_correspondence_by_category": dict(totals),
            "operations_totals": {
                "open_projects": sum(project_counts.values()),
                "overdue_projects": sum(overdue_projects.values()),
                "recorded_leases_ending_within_60_days": sum(len(v) for v in leases_ending.values()),
            },
            "source": "PM_PROPERTIES_AND_REVIEWED_CORRESPONDENCE_REPORTS",
            "coverage_note": "Only explicitly reviewed correspondence is included; no automated inbox scan was run.",
            "caveat": "No receivable, inspection, lease renewal or work-order conclusion can be inferred from reviewed email subjects alone.",
            "mail_sent": False, "ledger_modified": False,
        })
