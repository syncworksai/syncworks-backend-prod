"""Durable worker for approved, synthetic-only spreadsheet demonstration jobs."""
from __future__ import annotations

import base64
import csv
import io
import uuid
from datetime import timedelta
from django.db import connection, transaction
from django.utils import timezone
from user_accounts.models import FreelanceSyntheticJob
from .freelance_pilot_views import _clean_csv, _founder_authorized

LEASE_SECONDS = 90
MAX_JOBS_PER_TICK = 5

def sample_csv(count, seed):
    if not (1 <= count <= 1000 and 0 <= seed <= 999999):
        raise ValueError("Invalid synthetic dataset settings")
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["record_id", "name", "email", "amount"])
    for i in range(count):
        key = i if i % 10 else max(0, i - 1)
        writer.writerow([f"SYN-{key + seed:06d}", f" Synthetic Person {key} ",
                         f"PERSON{key}@example.invalid", "125.00"])
    return output.getvalue().encode("utf-8")

def make_report(job):
    processed = _clean_csv(sample_csv(job.row_count, job.seed))
    report = processed["report"].copy()
    # Keep receipts only; source/output bytes are regenerated when downloaded.
    return {
        "source_rows": report["source_rows"],
        "cleaned_rows": report["cleaned_rows"],
        "duplicates_removed": report["duplicate_rows_removed"],
        "empty_rows_removed": report["empty_rows_removed"],
        "flagged_count": report["flagged_count"],
        "output_sha256": report["sha256"],
        "ai_provider_cost_cents": 0,
        "synthetic_only": True,
        "review_required": True,
    }

def claim():
    now = timezone.now()
    with transaction.atomic():
        query = FreelanceSyntheticJob.objects.filter(state="QUEUED").order_by("created_at")
        if connection.features.has_select_for_update_skip_locked:
            query = query.select_for_update(skip_locked=True)
        else:
            query = query.select_for_update()
        job = query.first()
        if not job:
            return None
        # Do not process queued tasks belonging to deauthorized users.
        if not _founder_authorized(job.owner):
            job.state = "CANCELLED"
            job.error_code = "not_authorized"
            job.save(update_fields=["state", "error_code", "updated_at"])
            return None
        token = uuid.uuid4()
        job.state = "RUNNING"
        job.lease_token = token
        job.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        job.attempts += 1
        job.save(update_fields=["state", "lease_token", "lease_expires_at", "attempts", "updated_at"])
        return job.pk, token

def recover_expired():
    now = timezone.now()
    qs = FreelanceSyntheticJob.objects.filter(state="RUNNING", lease_expires_at__lte=now)
    with transaction.atomic():
        qs = qs.select_for_update()
        for job in qs[:20]:
            job.lease_token = None
            job.lease_expires_at = None
            job.state = "FAILED" if job.attempts >= 2 else "QUEUED"
            job.error_code = "lease_expired"
            job.save()

def run_one(job_id, token):
    job = FreelanceSyntheticJob.objects.select_related("owner").get(pk=job_id)
    if job.state != "RUNNING" or job.lease_token != token:
        return "lost_lease"
    try:
        outcome = make_report(job)
        error = ""
    except Exception:
        outcome = None
        error = "processing_failed"
    with transaction.atomic():
        current = FreelanceSyntheticJob.objects.select_for_update().get(pk=job_id)
        if current.state != "RUNNING" or current.lease_token != token:
            return "lost_lease"
        current.lease_token = None
        current.lease_expires_at = None
        if outcome is not None:
            current.result = outcome
            current.state = "REVIEW"
            current.error_code = ""
        else:
            current.error_code = error
            current.state = "FAILED" if current.attempts >= 2 else "QUEUED"
        current.save()
        return current.state

def run_batch(limit=1):
    recover_expired()
    results = []
    for _ in range(min(MAX_JOBS_PER_TICK,max(0,int(limit)))):
        claimed = claim()
        if not claimed:
            break
        results.append(run_one(*claimed))
    return results
