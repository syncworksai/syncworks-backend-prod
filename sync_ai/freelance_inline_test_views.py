"""Feature-gated, founder-authenticated single synthetic test execution.

This endpoint is strictly for deterministic pilot validation when the separately
hosted scheduled cron has no DB connection. It does not run the general queue,
read client files, invoke AI providers, submit to Upwork, or auto-approve output.
Disable FREELANCE_SYNTHETIC_INLINE_TEST_ENABLED after the smoke test.
"""
from django.conf import settings
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import FreelanceSyntheticJob
from .freelance_pilot_views import FounderFreelancePermission, FreelanceThrottle, _feature_enabled
from .freelance_synthetic_queue import claim, run_one
from .freelance_synthetic_views import view

class FreelanceSyntheticInlineTestView(APIView):
    permission_classes = [IsAuthenticated, FounderFreelancePermission]
    throttle_classes = [FreelanceThrottle]

    def post(self, request, job_id):
        if not _feature_enabled("FREELANCE_SYNTHETIC_INLINE_TEST_ENABLED"):
            return Response({"detail": "One-time test execution is disabled."}, status=403)
        if request.data.get("consent_synthetic_only") is not True:
            return Response({"detail": "Explicit approval for this synthetic-only test is required."}, status=400)
        job = FreelanceSyntheticJob.objects.filter(pk=job_id, owner=request.user).first()
        if not job:
            return Response({"detail": "Test job not found."}, status=404)
        if job.state != "QUEUED":
            return Response({"detail": "Only queued synthetic jobs may execute."}, status=409)
        if not (1 <= job.row_count <= 1000 and 0 <= job.seed <= 999999):
            return Response({"detail": "Invalid synthetic job parameters."}, status=400)
        claimed = claim(target_job_id=job.pk)
        if not claimed:
            return Response({"detail": "Job already claimed or unavailable."}, status=409)
        result = run_one(*claimed)
        updated = FreelanceSyntheticJob.objects.get(pk=job.pk)
        return Response({"job": view(updated), "execution_result": result,
                         "synthetic_only": True,
                         "provider_spend_cents": 0,
                         "no_client_delivery": True})
