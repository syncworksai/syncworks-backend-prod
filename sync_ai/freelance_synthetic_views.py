"""Owner-only synthetic work queue API. No customer documents or paid AI calls."""
from __future__ import annotations
import base64
from uuid import UUID
from django.db import transaction
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from user_accounts.models import FreelanceSyntheticJob
from .freelance_pilot_views import FounderFreelancePermission, FreelanceThrottle, _snapshot
from .freelance_synthetic_queue import sample_csv, _clean_csv

def view(job):
    return {
        "id": str(job.pk), "project_id": str(job.project_id) if job.project_id else None,
        "state": job.state, "row_count": job.row_count,
        "attempts": job.attempts, "result": job.result if job.state in {"REVIEW", "APPROVED"} else {},
        "created_at": job.created_at.isoformat(), "updated_at": job.updated_at.isoformat(),
        "approved_at": job.approved_at.isoformat() if job.approved_at else None,
        "error_code": job.error_code,
    }

def jobs(user):
    return FreelanceSyntheticJob.objects.filter(owner=user).order_by("-created_at")

class FreelanceSyntheticJobsView(APIView):
    permission_classes = [IsAuthenticated, FounderFreelancePermission]
    throttle_classes = [FreelanceThrottle]

    def get(self, request):
        return Response({"jobs": [view(j) for j in jobs(request.user)[:30]],
                         "worker_requires_opt_in": True, "provider_spend_cents": 0})

    def post(self, request):
        if request.data.get("consent_synthetic_only") is not True:
            return Response({"detail": "Explicit synthetic-only execution consent required."}, status=400)
        try:
            count = int(request.data.get("row_count", 500))
            seed = int(request.data.get("seed", 42))
        except (ValueError, TypeError):
            return Response({"detail": "Invalid row count or seed."}, status=400)
        if not 1 <= count <= 1000 or not 0 <= seed <= 999999:
            return Response({"detail": "Synthetic task is limited to 1-1000 records and valid seed."}, status=400)
        project_id = request.data.get("project_id")
        if project_id:
            try:
                project_id = UUID(str(project_id))
            except ValueError:
                return Response({"detail": "Invalid project id."}, status=400)
            if str(project_id) not in {p["id"] for p in _snapshot(request.user)}:
                return Response({"detail": "Project is not accessible."}, status=404)
        with transaction.atomic():
            user = type(request.user).objects.select_for_update().get(pk=request.user.pk)
            if jobs(user).count() >= 50:
                return Response({"detail": "Synthetic pilot job limit reached."}, status=429)
            job = FreelanceSyntheticJob.objects.create(
                owner=user, row_count=count, seed=seed, project_id=project_id,
            )
        return Response({"job": view(job), "note": "Queued; worker must be enabled separately."}, status=201)

class FreelanceSyntheticJobView(APIView):
    permission_classes = [IsAuthenticated, FounderFreelancePermission]
    throttle_classes = [FreelanceThrottle]

    def get(self, request, job_id):
        job = jobs(request.user).filter(pk=job_id).first()
        if not job:
            return Response({"detail": "Job not found."}, status=404)
        return Response({"job": view(job)})

    def post(self, request, job_id):
        decision = str(request.data.get("decision", "")).strip()
        if decision not in {"approve", "cancel"}:
            return Response({"detail": "Choose approve or cancel."}, status=400)
        with transaction.atomic():
            job = jobs(request.user).select_for_update().filter(pk=job_id).first()
            if not job:
                return Response({"detail": "Job not found."}, status=404)
            if decision == "approve":
                if job.state != "REVIEW":
                    return Response({"detail": "Job must be awaiting review."}, status=409)
                from django.utils import timezone
                job.approved_at = timezone.now()
                job.state = "APPROVED"
                job.save(update_fields=["state", "approved_at", "updated_at"])
            else:
                if job.state not in {"QUEUED", "REVIEW", "FAILED"}:
                    return Response({"detail": "Cannot cancel this job state."}, status=409)
                job.state = "CANCELLED"
                job.save(update_fields=["state", "updated_at"])
        return Response({"job": view(job)})

class FreelanceSyntheticDownloadView(APIView):
    permission_classes = [IsAuthenticated, FounderFreelancePermission]
    throttle_classes = [FreelanceThrottle]

    def get(self, request, job_id):
        job = jobs(request.user).filter(pk=job_id, state="APPROVED").first()
        if not job or not job.result:
            return Response({"detail": "An approved result is required."}, status=404)
        # Result is regenerated deterministically. Never load a user-supplied file.
        output = _clean_csv(sample_csv(job.row_count, job.seed))
        if output["report"]["sha256"] != job.result.get("output_sha256"):
            return Response({"detail": "Result failed integrity verification."}, status=409)
        return Response({"filename": "synthetic-cleaned.csv", "content_base64": output["cleaned_csv_base64"],
                         "report": job.result, "synthetic_only": True})
