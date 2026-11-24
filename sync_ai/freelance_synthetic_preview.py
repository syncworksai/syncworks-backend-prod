"""Founder-only review preview for generated synthetic CSV results.

Allows inspecting output BEFORE approval, without publishing a downloadable
artifact or accepting customer-supplied data. Regenerates deterministic rows
and validates content against the stored execution receipt.
"""
import csv
import hashlib
import io
from django.utils.crypto import constant_time_compare
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import FreelanceSyntheticJob
from .freelance_pilot_views import FounderFreelancePermission, FreelanceThrottle, _clean_csv
from .freelance_synthetic_queue import sample_csv


class FreelanceSyntheticPreviewView(APIView):
    permission_classes = [IsAuthenticated, FounderFreelancePermission]
    throttle_classes = [FreelanceThrottle]

    def get(self, request, job_id):
        job = FreelanceSyntheticJob.objects.filter(owner=request.user, pk=job_id, state__in=["REVIEW", "APPROVED"]).first()
        if not job or not job.result:
            return Response({"detail": "A processed synthetic result is required."}, status=404)

        processed = _clean_csv(sample_csv(job.row_count, job.seed))
        receipt = str(job.result.get("output_sha256") or "")
        actual_hash = processed["report"]["sha256"]
        if len(receipt) != 64 or not constant_time_compare(receipt, actual_hash):
            return Response({"detail": "Result failed integrity verification."}, status=409)

        import base64
        content = base64.b64decode(processed["cleaned_csv_base64"]).decode("utf-8")
        rows = list(csv.DictReader(io.StringIO(content)))
        columns = ["record_id", "name", "email", "amount"]
        ids = [row["record_id"] for row in rows]
        check_results = [
            {"key": "integrity", "label": "Output fingerprint matches execution receipt", "passed": True},
            {"key": "rows", "label": "Cleaned row count matches report", "passed": len(rows) == job.result.get("cleaned_rows")},
            {"key": "accounting", "label": "Removed and retained rows reconcile", "passed": job.row_count == len(rows) + job.result.get("duplicates_removed", -1) + job.result.get("empty_rows_removed", -1)},
            {"key": "unique", "label": "Record IDs are unique after cleanup", "passed": len(ids) == len(set(ids))},
            {"key": "complete", "label": "All output fields are present", "passed": all(all(str(row.get(k, "")).strip() for k in columns) for row in rows)},
            {"key": "synthetic", "label": "Only synthetic email domains appear", "passed": all(row["email"].endswith("@example.invalid") for row in rows)},
        ]
        return Response({
            "synthetic_only": True,
            "state": job.state,
            "columns": columns,
            "preview_rows": rows[:8],
            "tail_rows": rows[-3:] if len(rows) > 8 else [],
            "total_rows": len(rows),
            "report": job.result,
            "checks": check_results,
            "all_passed": all(item["passed"] for item in check_results),
            "no_external_delivery": True,
        })
