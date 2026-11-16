"""Database-backed, bounded Sync Assist job dispatch.

The queue is persistent across application restarts. Only read-only internal
specialists may run unattended in v1. The public-search adapter deliberately
remains on-demand because it needs a separate provider budget and lease policy.
"""
from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

from django.db import connection, transaction
from django.utils import timezone

from user_accounts.models import SyncAssistJob
from .assist_workday_views import _snapshot

RUNNING_LEASE_SECONDS = 90
MAX_BATCH = 20


def serialize_job(job):
    return {
        "id": str(job.id), "goal_id": str(job.goal_id), "state": job.state,
        "attempts": job.attempts, "max_attempts": job.max_attempts,
        "next_run_at": job.next_run_at.isoformat(),
        "lease_expires_at": job.lease_expires_at.isoformat() if job.lease_expires_at else None,
        "last_error": job.last_error, "last_receipt_id": str(job.last_receipt_id) if job.last_receipt_id else None,
        "updated_at": job.updated_at.isoformat(),
    }


def enqueue_goal(owner, goal_id):
    """Idempotent per-owner/goal queue insertion or resumption."""
    goal_id = UUID(str(goal_id))
    with transaction.atomic():
        goal = next((g for g in _snapshot(owner)["goals"] if g["id"] == str(goal_id)), None)
        if not goal:
            return None, "not_found"
        if goal["source_mode"] != "INTERNAL_ONLY":
            return None, "external_research_not_approved_for_unattended_use"
        if goal["status"] == "COMPLETED":
            existing = SyncAssistJob.objects.select_for_update().filter(owner=owner, goal_id=goal_id).first()
            if existing and existing.state != SyncAssistJob.State.CANCELLED:
                existing.state = SyncAssistJob.State.SUCCEEDED
                existing.lease_token = None
                existing.lease_expires_at = None
                existing.last_error = ""
                existing.save(update_fields=["state", "lease_token", "lease_expires_at", "last_error", "updated_at"])
            return existing, "goal_already_completed"
        if not any(s["role"] in {"RESEARCH_ANALYST", "SALES_MANAGER", "MARKETING_MANAGER", "CHIEF_OF_STAFF", "EXECUTIVE_ASSISTANT"} for s in goal["steps"]):
            return None, "no_supported_employee"
        job, created = SyncAssistJob.objects.select_for_update().get_or_create(
            owner=owner, goal_id=goal_id,
            defaults={"state": SyncAssistJob.State.QUEUED},
        )
        if not created:
            if job.state == SyncAssistJob.State.RUNNING:
                return job, "already_running"
            if job.state in {SyncAssistJob.State.CANCELLED, SyncAssistJob.State.FAILED}:
                return job, "explicit_restart_required"
            job.state = SyncAssistJob.State.QUEUED
            job.next_run_at = timezone.now()
            job.lease_token = None
            job.lease_expires_at = None
            job.last_error = ""
            job.save(update_fields=["state", "next_run_at", "lease_token", "lease_expires_at", "last_error", "updated_at"])
        return job, "created" if created else "resumed"


def cancel_goal_job(owner, goal_id):
    with transaction.atomic():
        job = SyncAssistJob.objects.select_for_update().filter(owner=owner, goal_id=UUID(str(goal_id))).first()
        if not job:
            return None
        if job.state not in {SyncAssistJob.State.CANCELLED, SyncAssistJob.State.SUCCEEDED}:
            job.state = SyncAssistJob.State.CANCELLED
            job.lease_token = None
            job.lease_expires_at = None
            job.save(update_fields=["state", "lease_token", "lease_expires_at", "updated_at"])
        return job


def _lock_candidates(qs):
    if connection.features.has_select_for_update_skip_locked:
        return qs.select_for_update(skip_locked=True)
    return qs.select_for_update()


def claim_one():
    now = timezone.now()
    with transaction.atomic():
        stale = _lock_candidates(SyncAssistJob.objects.filter(
            state=SyncAssistJob.State.RUNNING, lease_expires_at__lte=now
        ).order_by("created_at")).first()
        if stale:
            stale.state = SyncAssistJob.State.FAILED if stale.attempts >= stale.max_attempts else SyncAssistJob.State.RETRY
            stale.next_run_at = now + timedelta(seconds=30)
            stale.lease_token = None
            stale.lease_expires_at = None
            stale.last_error = "Worker lease expired; job needs re-evaluation."
            stale.save()
        candidates = SyncAssistJob.objects.filter(
            state__in=[SyncAssistJob.State.QUEUED, SyncAssistJob.State.RETRY],
            next_run_at__lte=now,
        ).order_by("next_run_at", "created_at")
        job = _lock_candidates(candidates).first()
        if not job:
            return None
        job.state = SyncAssistJob.State.RUNNING
        job.lease_token = uuid4()
        job.lease_expires_at = now + timedelta(seconds=RUNNING_LEASE_SECONDS)
        job.save(update_fields=["state", "lease_token", "lease_expires_at", "updated_at"])
        return job.pk, job.lease_token


def run_claimed(job_id, token):
    """Run one deterministic assignment, then reconcile only our own lease."""
    job = SyncAssistJob.objects.select_related("owner").get(pk=job_id)
    if job.state != SyncAssistJob.State.RUNNING or job.lease_token != token:
        return "lost_lease"
    # Refuse public network requests in the unattended worker, regardless of flags.
    goal = next((g for g in _snapshot(job.owner)["goals"] if g["id"] == str(job.goal_id)), None)
    if goal is None or goal.get("source_mode") != "INTERNAL_ONLY":
        result = {"code": "invalid_scope", "detail": "Unattended execution only permits internal records."}
    else:
        try:
            from .assist_workday_execution import execute_one
            result = execute_one(job.owner, str(job.goal_id))
        except Exception:
            result = {"code": "error", "detail": "Worker failed. See private server logs."}
    with transaction.atomic():
        fresh = SyncAssistJob.objects.select_for_update().get(pk=job_id)
        if fresh.state != SyncAssistJob.State.RUNNING or fresh.lease_token != token:
            return "cancelled_or_lost_lease"
        fresh.lease_expires_at = None
        fresh.lease_token = None
        code = result.get("code")
        if code == "executed":
            receipt = result["receipt"]
            fresh.last_receipt_id = UUID(receipt["receipt_id"])
            fresh.attempts = 0
            fresh.last_error = ""
            # Owner must inspect every output before a specialist handoff.
            fresh.state = SyncAssistJob.State.WAITING
        elif code in {"no_action", "budget_exhausted"}:
            fresh.state = SyncAssistJob.State.WAITING
            fresh.last_error = str(result.get("detail", ""))[:300]
        elif code in {"not_found", "invalid_scope"}:
            fresh.state = SyncAssistJob.State.FAILED
            fresh.last_error = str(result.get("detail", ""))[:300]
        else:
            fresh.attempts += 1
            fresh.last_error = str(result.get("detail", "Worker error"))[:300]
            if fresh.attempts >= fresh.max_attempts:
                fresh.state = SyncAssistJob.State.FAILED
            else:
                fresh.state = SyncAssistJob.State.RETRY
                fresh.next_run_at = timezone.now() + timedelta(seconds=min(3600, 30 * 2 ** (fresh.attempts - 1)))
        fresh.save()
        return fresh.state


def run_batch(limit=1):
    results = []
    for _ in range(min(MAX_BATCH, max(0, int(limit)))):
        claimed = claim_one()
        if claimed is None:
            break
        results.append(run_claimed(*claimed))
    return results
