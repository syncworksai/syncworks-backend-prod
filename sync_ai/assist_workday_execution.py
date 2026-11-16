"""Constrained, auditable Sync Assist internal task runner.

First vertical slice: no external network, email, billing, or third-party write
capabilities. Only authorized owner-entered prospect records can feed reports.
One bounded action runs per invocation. Scheduled execution is opt-in.
"""
from __future__ import annotations

import os
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db import transaction
from user_accounts.models import AuditLog
from .assist_growth_prospects import CREATE as PROSPECT_CREATED, UPDATE as PROSPECT_UPDATED
from .assist_workday_views import CREATED, PROGRESS, _snapshot

WORKED = "sync_assist.workday.worker_receipt"
MAX_PROSPECTS = 15
MAX_ATTEMPTS = 3
MAX_PUBLIC_REQUESTS_PER_DAY = 10
SUPPORTED = {"RESEARCH_ANALYST", "SALES_MANAGER", "CHIEF_OF_STAFF"}
WORKFLOW_VERSION = "internal-prospect-v1"


def _latest_prospects(user):
    """Return only explicit owner-entered prospects, never inferred contacts."""
    rows = {}
    for event in AuditLog.objects.filter(
        actor=user, action__in=[PROSPECT_CREATED, PROSPECT_UPDATED]
    ).order_by("id"):
        m = event.metadata or {}
        key = str(m.get("prospect_id") or "")
        if event.action == PROSPECT_CREATED and key:
            rows[key] = {
                "id": key,
                "company": str(m.get("company") or "")[:140],
                "niche": str(m.get("niche") or ""),
                "website": str(m.get("website") or "")[:300],
                "observation": str(m.get("observation") or "")[:350],
                "draft": str(m.get("draft") or "")[:1200],
                "stage": str(m.get("stage") or ""),
                "audit_event_id": event.pk,
            }
        elif key in rows:
            rows[key]["stage"] = str(m.get("stage") or rows[key]["stage"])
    return [
        item for item in reversed(list(rows.values()))
        if item["stage"] not in {"DO_NOT_CONTACT", "NOT_INTERESTED", "CLOSED_WON"}
    ][:MAX_PROSPECTS]


def _research(user, goal, _step):
    if goal.get("source_mode") == "PUBLIC_SEARCH":
        from .assist_public_search import ResearchDisabled, public_search
        try:
            found = public_search(goal.get("public_search_query", ""))
        except ResearchDisabled as exc:
            return {"status": "BLOCKED", "message": str(exc), "output": [], "sources": []}
        if not found:
            return {"status": "BLOCKED", "message": "No usable public results. Refine the explicit query.", "output": [], "sources": []}
        return {
            "status": "AWAITING_APPROVAL",
            "message": "Collected public search listings with source links. Business identities and contact details remain unverified.",
            "output": found,
            "sources": [{"type": "public_search_result", "url": item["website"], "provider": "serper",
                         "verification": "search_snippet_only"} for item in found],
        }
    prospects = _latest_prospects(user)
    if not prospects:
        return {
            "status": "BLOCKED",
            "message": "No eligible owner-entered prospects. Add sourced companies in Growth Center, then retry.",
            "output": [],
            "sources": [],
        }
    return {
        "status": "AWAITING_APPROVAL",
        "message": "Compiled owner-entered prospect records. Website claims were not independently checked.",
        "output": [
            {
                "company": p["company"], "niche": p["niche"], "website": p["website"],
                "observation": p["observation"], "stage": p["stage"],
                "provenance": "owner_entered_unverified",
                "prospect_id": p["id"],
            }
            for p in prospects
        ],
        "sources": [
            {"type": "syncworks_audit_event", "id": p["audit_event_id"],
             "prospect_id": p["id"], "website": p["website"],
             "verification": "owner_entered_unverified"}
            for p in prospects
        ],
    }


def _source_output(user, goal, preceding_role):
    """Only owner-attested, worker-produced outputs from this same goal count."""
    preceding = [s for s in goal["steps"] if s["role"] == preceding_role and s["status"] == "COMPLETED"
                 and s.get("verified_by") == "owner"]
    if not preceding:
        return None
    target = preceding[0]
    receipt = target.get("worker_receipt") or {}
    if receipt.get("status") != "AWAITING_APPROVAL" or receipt.get("workflow_version") != WORKFLOW_VERSION:
        return None
    return receipt


def _sales(user, goal, _step):
    source = _source_output(user, goal, "RESEARCH_ANALYST")
    if not source:
        return {
            "status": "BLOCKED", "message": "Research must be executed and owner-attested first.",
            "output": [], "sources": [],
        }
    source_ids = {x.get("prospect_id") for x in source.get("output", []) if isinstance(x, dict)}
    current = [p for p in _latest_prospects(user) if p["id"] in source_ids]
    drafts = [
        {"prospect_id": p["id"], "company": p["company"], "draft": p["draft"],
         "channel": "OWNER_REVIEW_ONLY", "sent": False}
        for p in current if p["draft"]
    ]
    # Public search listings are not automatically qualified, imported, or contacted.
    # Draft without assuming that a search title represents a verified company.
    for entry in source.get("output", []):
        if not isinstance(entry, dict) or entry.get("provenance") != "public_search_result_unverified":
            continue
        link = entry.get("website", "")
        if not isinstance(link, str) or not link.startswith("https://"):
            continue
        drafts.append({
            "company": str(entry.get("title") or "")[:180],
            "source_url": link,
            "draft": ("Hello, I'm reaching out from SyncWorks. We're building tools that help "
                      "service businesses coordinate customers, scheduling and operations. "
                      "If your team is interested, would you be open to a brief introduction?"),
            "channel": "OWNER_REVIEW_ONLY", "sent": False,
            "needs_business_identity_verification": True,
        })
    drafts = drafts[:MAX_PROSPECTS]
    if not drafts:
        return {"status": "BLOCKED", "message": "No currently eligible outreach drafts.", "output": [], "sources": []}
    return {
        "status": "AWAITING_APPROVAL",
        "message": "Prepared previously generated outreach drafts for owner review. No messages sent.",
        "output": drafts,
        "sources": [{"type": "approved_workday_receipt", "step_id": source["step_id"],
                     "receipt_id": source["receipt_id"]}],
    }


def _chief(user, goal, _step):
    receipts = [
        s["worker_receipt"] for s in goal["steps"]
        if s["role"] in {"RESEARCH_ANALYST", "SALES_MANAGER"} and s["status"] == "COMPLETED"
        and s.get("verified_by") == "owner" and s.get("worker_receipt")
    ]
    if not receipts:
        return {
            "status": "BLOCKED", "message": "No approved specialist results to summarize.",
            "output": [], "sources": [],
        }
    items = []
    for receipt in receipts:
        items.append({"employee": receipt["role"], "records": len(receipt.get("output", [])),
                      "result": receipt.get("message", ""), "source_receipt_id": receipt["receipt_id"]})
    return {
        "status": "AWAITING_APPROVAL",
        "message": "Compiled owner-verified activity; this is not proof of external delivery or sales.",
        "output": items,
        "sources": [{"type": "approved_workday_receipt", "receipt_id": x["receipt_id"]} for x in receipts],
    }


HANDLERS = {"RESEARCH_ANALYST": _research, "SALES_MANAGER": _sales, "CHIEF_OF_STAFF": _chief}


def execute_one(user, goal_id):
    """Execute at most one internal action, protected by account row lock.

    Snapshot and receipt creation happen atomically; existing receipts are not
    replayed. No user-controlled URL is fetched or executed.
    """
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=user.pk)
        goal = next((g for g in _snapshot(user)["goals"] if g["id"] == goal_id), None)
        if not goal:
            return {"code": "not_found", "detail": "Goal not found."}
        candidate = next((
            s for s in goal["steps"]
            if s["role"] in SUPPORTED and s["status"] in {"PLANNED", "BLOCKED"}
        ), None)
        if candidate is None:
            return {"code": "no_action", "detail": "No eligible internal action. Review completed or awaiting-approval steps first."}
        attempts = AuditLog.objects.filter(
            actor=user, action=WORKED,
            metadata__goal_id=goal_id, metadata__step_id=candidate["id"],
        ).count()
        if attempts >= MAX_ATTEMPTS:
            return {"code": "attempt_limit", "detail": "Internal action retry limit reached."}
        public_attempt = (
            candidate["role"] == "RESEARCH_ANALYST"
            and goal.get("source_mode") == "PUBLIC_SEARCH"
            and os.environ.get("SYNC_ASSIST_LIVE_RESEARCH_ENABLED") == "true"
            and bool(os.environ.get("SERPER_API_KEY", "").strip())
        )
        if public_attempt:
            used_today = AuditLog.objects.filter(
                actor=user, action=WORKED,
                metadata__provider_requests=1,
                created_at__gte=timezone.now() - timedelta(days=1),
            ).count()
            if used_today >= MAX_PUBLIC_REQUESTS_PER_DAY:
                return {"code": "budget_exhausted", "detail": "Daily public research request budget reached."}
        try:
            result = HANDLERS[candidate["role"]](user, goal, candidate)
        except Exception:
            # Do not publish raw internal errors or fabricate a completion.
            result = {"status": "BLOCKED", "message": "Internal worker error. Review server logs.",
                      "output": [], "sources": []}
        from uuid import uuid4
        receipt = {
            "receipt_id": str(uuid4()),
            "workflow_version": WORKFLOW_VERSION, "goal_id": goal_id,
            "step_id": candidate["id"], "role": candidate["role"],
            "status": result["status"], "message": result["message"],
            "output": result["output"], "sources": result["sources"],
            "external_actions": 0, "messages_sent": 0,
            "model_calls": 0, "reported_model_cost_usd": "0.00",
            "provider_requests": 1 if public_attempt else 0,
            "execution_type": "deterministic_internal_read_or_draft",
        }
        AuditLog.objects.create(actor=user, action=WORKED, metadata=receipt)
        # The receipt itself describes a draft/checkpoint, never a verified completion.
        return {"code": "executed", "receipt": receipt}
