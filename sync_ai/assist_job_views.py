"""Private-pilot API for explicit durable-worker enrollment and cancellation."""
from uuid import UUID
from datetime import timedelta

from django.utils import timezone

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import SyncAssistJob, AuditLog
from .assist_pilot_views import _pilot
from .assist_job_queue import cancel_goal_job, enqueue_goal, serialize_job


class SyncAssistJobView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _pilot(request.user):
            return Response({"detail": "Private pilot only."}, status=403)
        jobs = SyncAssistJob.objects.filter(owner=request.user).order_by("-created_at")[:100]
        ticks = list(AuditLog.objects.filter(
            actor=request.user, action="sync_assist.queue.worker_tick",
            created_at__gte=timezone.now() - timedelta(minutes=30),
            metadata__run_source="independent_worker",
        ).order_by("-id")[:2])
        observed = len(ticks) >= 2
        return Response({
            "jobs": [serialize_job(job) for job in jobs],
            "worker_deployed": observed,
            "worker_status": "recent_runs_observed" if observed else "not_verified",
            "last_worker_run": ticks[0].created_at.isoformat() if ticks else None,
            "scheduling_enabled": observed,
            "external_actions_enabled": False,
            "notice": "Worker status is derived from recorded runs, not the deployment configuration. Two independent runs in 30 minutes are required for a recent activity indicator.",
        })

    def post(self, request):
        if not _pilot(request.user):
            return Response({"detail": "Private pilot only."}, status=403)
        try:
            goal_id = UUID(str(request.data.get("goal_id", "")))
        except (TypeError, ValueError, AttributeError):
            return Response({"detail": "Valid goal_id required."}, status=400)
        if request.data.get("allow_background_internal") is not True:
            return Response({"detail": "Explicit background internal-work consent is required."}, status=400)
        job, status = enqueue_goal(request.user, goal_id)
        if not job or status == "explicit_restart_required":
            return Response({"detail": status}, status=409 if job else 400)
        return Response({"job": serialize_job(job), "result": status}, status=201 if status == "created" else 200)


class SyncAssistJobCancelView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, goal_id):
        if not _pilot(request.user):
            return Response({"detail": "Private pilot only."}, status=403)
        try:
            key = UUID(str(goal_id))
        except (TypeError, ValueError, AttributeError):
            return Response({"detail": "Invalid goal ID."}, status=400)
        job = cancel_goal_job(request.user, key)
        if not job:
            return Response({"detail": "Job not found."}, status=404)
        return Response({"job": serialize_job(job)})
