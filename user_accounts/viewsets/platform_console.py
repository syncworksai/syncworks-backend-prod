# backend/user_accounts/viewsets/platform_console.py
from __future__ import annotations

import json
import os
from urllib import error as urllib_error
from urllib import request as urllib_request

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count
from django.utils import timezone

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import Business, PlatformBillingProfile, Notification
from user_accounts.permissions import IsGodMode  # ✅ import from module (NOT package)

from user_accounts.serializers.platform_console import (
    PlatformUserSerializer,
    PlatformBusinessSerializer,
)

User = get_user_model()

DEVELOPER_AGENT_REPOSITORY = "syncworksai/Syncworks-developer-agent"
DEVELOPER_AGENT_WORKFLOW = "run-approved-task.yml"
DEVELOPER_AGENT_REF = "main"
DEVELOPER_AGENT_TIMEOUT_SECONDS = 10
DEVELOPER_AGENT_ALLOWLIST = {
    "business-growth-backend-persistence-001": "tasks/approved/business-growth-backend-persistence-001.json",
    "god-mode-developer-agent-panel-001": "tasks/approved/god-mode-developer-agent-panel-001.json",
    "business-setup-ui-001": "tasks/approved/business-setup-ui-001.json",
}
DEVELOPER_AGENT_API_BASE = f"https://api.github.com/repos/{DEVELOPER_AGENT_REPOSITORY}"
DEVELOPER_AGENT_WORKFLOW_DISPATCH_URL = (
    f"{DEVELOPER_AGENT_API_BASE}/actions/workflows/{DEVELOPER_AGENT_WORKFLOW}/dispatches"
)
DEVELOPER_AGENT_RUNS_URL = f"{DEVELOPER_AGENT_API_BASE}/actions/workflows/{DEVELOPER_AGENT_WORKFLOW}/runs"


class PlatformDeveloperAgentRunAPIView(APIView):
    permission_classes = [IsAuthenticated, IsGodMode]

    def post(self, request):
        task_id = (request.data.get("task_id") or "").strip()
        if not task_id:
            return Response({"detail": "task_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        task_path = DEVELOPER_AGENT_ALLOWLIST.get(task_id)
        if not task_path:
            return Response({"detail": "Unknown task_id."}, status=status.HTTP_400_BAD_REQUEST)

        token = os.environ.get("SYNCWORKS_DEVELOPER_AGENT_TOKEN")
        if not token:
            return Response(
                {"detail": "Developer agent is not configured.", "configured": False},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            recent_runs = self._fetch_recent_runs(token, per_page=10)
        except urllib_error.HTTPError:
            return Response(
                {"detail": "Unable to verify workflow state."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except urllib_error.URLError:
            return Response(
                {"detail": "Unable to reach GitHub."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except json.JSONDecodeError:
            return Response(
                {"detail": "Malformed workflow response."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except Exception:
            return Response(
                {"detail": "Unexpected error while checking workflow state."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        for run in recent_runs:
            if run.get("status") in {"queued", "in_progress"}:
                return Response(
                    {"detail": "A workflow dispatch is already in progress."},
                    status=status.HTTP_409_CONFLICT,
                )

        try:
            self._dispatch_workflow(token, task_path)
        except urllib_error.HTTPError as exc:
            if getattr(exc, "code", None) == 204:
                return Response({"accepted": True, "task_id": task_id}, status=status.HTTP_202_ACCEPTED)
            return Response(
                {"detail": "Workflow dispatch failed."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except urllib_error.URLError:
            return Response(
                {"detail": "Unable to reach GitHub."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception:
            return Response(
                {"detail": "Unexpected error while dispatching workflow."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({"accepted": True, "task_id": task_id}, status=status.HTTP_202_ACCEPTED)

    def _auth_headers(self, token):
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "syncworks-developer-agent-dispatcher",
        }

    def _fetch_recent_runs(self, token, per_page=10):
        url = f"{DEVELOPER_AGENT_RUNS_URL}?event=workflow_dispatch&per_page={int(per_page)}"
        req = urllib_request.Request(url, headers=self._auth_headers(token), method="GET")
        with urllib_request.urlopen(req, timeout=DEVELOPER_AGENT_TIMEOUT_SECONDS) as resp:
            data = resp.read().decode("utf-8")
        payload = json.loads(data)
        return payload.get("workflow_runs", []) if isinstance(payload, dict) else []

    def _dispatch_workflow(self, token, task_path):
        payload = json.dumps({"ref": DEVELOPER_AGENT_REF, "inputs": {"task_path": task_path}}).encode("utf-8")
        req = urllib_request.Request(
            DEVELOPER_AGENT_WORKFLOW_DISPATCH_URL,
            data=payload,
            headers={**self._auth_headers(token), "Content-Type": "application/json"},
            method="POST",
        )
        with urllib_request.urlopen(req, timeout=DEVELOPER_AGENT_TIMEOUT_SECONDS) as resp:
            if getattr(resp, "status", None) != 204:
                raise urllib_error.HTTPError(
                    req.full_url,
                    getattr(resp, "status", 500),
                    "Unexpected response",
                    resp.headers,
                    None,
                )


class PlatformDeveloperAgentStatusAPIView(APIView):
    permission_classes = [IsAuthenticated, IsGodMode]

    def get(self, request):
        token = os.environ.get("SYNCWORKS_DEVELOPER_AGENT_TOKEN")
        configured = bool(token)
        recent_runs = []

        if configured:
            try:
                recent_runs = self._fetch_recent_runs(token, per_page=10)
            except Exception:
                recent_runs = []

        return Response(
            {
                "configured": configured,
                "repository": DEVELOPER_AGENT_REPOSITORY,
                "workflow": DEVELOPER_AGENT_WORKFLOW,
                "ref": DEVELOPER_AGENT_REF,
                "approved_task_ids": list(DEVELOPER_AGENT_ALLOWLIST.keys()),
                "safety_flags": {
                    "branch_only": True,
                    "draft_pr_only": True,
                    "auto_merge": False,
                    "auto_deploy": False,
                    "production_migrations": False,
                },
                "recent_runs": [
                    {
                        "id": run.get("id"),
                        "status": run.get("status"),
                        "conclusion": run.get("conclusion"),
                        "created_at": run.get("created_at"),
                        "updated_at": run.get("updated_at"),
                        "html_url": run.get("html_url"),
                        "head_branch": run.get("head_branch"),
                    }
                    for run in recent_runs[:10]
                    if isinstance(run, dict)
                ],
            },
            status=status.HTTP_200_OK,
        )

    def _auth_headers(self, token):
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "syncworks-developer-agent-dispatcher",
        }

    def _fetch_recent_runs(self, token, per_page=10):
        url = f"{DEVELOPER_AGENT_RUNS_URL}?event=workflow_dispatch&per_page={int(per_page)}"
        req = urllib_request.Request(url, headers=self._auth_headers(token), method="GET")
        with urllib_request.urlopen(req, timeout=DEVELOPER_AGENT_TIMEOUT_SECONDS) as resp:
            data = resp.read().decode("utf-8")
        payload = json.loads(data)
        return payload.get("workflow_runs", []) if isinstance(payload, dict) else []


class PlatformUsersViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/v1/platform/users/?q=...
    God Mode user directory.
    """
    permission_classes = [IsAuthenticated, IsGodMode]
    serializer_class = PlatformUserSerializer

    def get_queryset(self):
        qs = User.objects.all().order_by("-date_joined")
        q = (self.request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(email__icontains=q)
        return qs


class PlatformBusinessesViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/v1/platform/businesses/?q=...
    Includes billing lock state (via serializer).
    """
    permission_classes = [IsAuthenticated, IsGodMode]
    serializer_class = PlatformBusinessSerializer

    def get_queryset(self):
        qs = Business.objects.all().order_by("-created_at")
        q = (self.request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(name__icontains=q)
        return qs

    @action(detail=True, methods=["post"], url_path="lock")
    def lock_business(self, request, pk=None):
        reason = (request.data.get("reason") or "Locked by platform admin").strip()
        biz = self.get_object()

        profile, _ = PlatformBillingProfile.objects.get_or_create(business=biz)

        # ✅ Support both implementations: profile.lock() helper OR direct fields
        if hasattr(profile, "lock") and callable(getattr(profile, "lock")):
            profile.lock(reason=reason)
        else:
            profile.is_locked = True
            profile.lock_reason = reason
            profile.locked_at = timezone.now()

        profile.save()

        return Response(
            {"detail": "Business locked.", "business_id": biz.id, "lock_reason": profile.lock_reason},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="unlock")
    def unlock_business(self, request, pk=None):
        biz = self.get_object()

        profile, _ = PlatformBillingProfile.objects.get_or_create(business=biz)

        # ✅ Support both implementations: profile.unlock() helper OR direct fields
        if hasattr(profile, "unlock") and callable(getattr(profile, "unlock")):
            profile.unlock()
        else:
            profile.is_locked = False
            profile.lock_reason = ""
            profile.locked_at = None

        profile.save()

        return Response(
            {"detail": "Business unlocked.", "business_id": biz.id},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="message-owner")
    def message_owner(self, request, pk=None):
        """
        POST /platform/businesses/:id/message-owner/
        { "title": "...", "body": "..." }
        Creates a Notification to ALL active members (best-effort).
        """
        biz = self.get_object()
        title = (request.data.get("title") or "").strip()
        body = (request.data.get("body") or "").strip()

        if not title or not body:
            return Response({"detail": "title and body are required."}, status=status.HTTP_400_BAD_REQUEST)

        member_users: list[int] = []
        try:
            member_users = list(biz.members.filter(is_active=True).values_list("user_id", flat=True))
        except Exception:
            member_users = []

        if not member_users:
            return Response({"detail": "No active members found for this business."}, status=status.HTTP_400_BAD_REQUEST)

        Notification.objects.bulk_create(
            [
                Notification(
                    recipient_id=uid,
                    actor=request.user,
                    type=Notification.TYPE_SYSTEM,
                    title=title,
                    body=body,
                    data={"business_id": biz.id},
                )
                for uid in member_users
            ],
            batch_size=500,
        )

        return Response({"detail": "Message sent.", "recipients": len(member_users)}, status=status.HTTP_201_CREATED)


class PlatformBillingSummaryViewSet(viewsets.ViewSet):
    """
    GET /api/v1/platform/billing/summary/
    Simple operational view:
    - locked businesses
    - businesses missing card
    """
    permission_classes = [IsAuthenticated, IsGodMode]

    def list(self, request):
        profiles = PlatformBillingProfile.objects.select_related("business").all()

        locked = profiles.filter(is_locked=True).count()
        no_card = profiles.filter(stripe_setup_complete=False).count()

        locked_list = [
            {
                "business_id": p.business_id,
                "business_name": getattr(p.business, "name", f"Business {p.business_id}"),
                "lock_reason": p.lock_reason,
                "locked_at": p.locked_at,
                "next_due_date": p.next_due_date,
                "grace_until": p.grace_until,
            }
            for p in profiles.filter(is_locked=True).order_by("-locked_at")[:100]
        ]

        return Response(
            {
                "locked_count": locked,
                "no_card_count": no_card,
                "locked_businesses": locked_list,
            },
            status=status.HTTP_200_OK,
        )


class PlatformKpiTimeseriesViewSet(viewsets.ViewSet):
    """
    GET /api/v1/platform/kpis/timeseries/?days=30
    Returns daily counts for charting.
    """
    permission_classes = [IsAuthenticated, IsGodMode]

    def list(self, request):
        days = int(request.query_params.get("days") or 30)
        days = max(7, min(days, 365))

        today = timezone.localdate()
        start = today - timedelta(days=days - 1)

        series = {
            start + timedelta(days=i): {"signups": 0, "businesses_created": 0, "locked_businesses": 0}
            for i in range(days)
        }

        users = (
            User.objects.filter(date_joined__date__gte=start, date_joined__date__lte=today)
            .values("date_joined__date")
            .annotate(c=Count("id"))
        )
        for row in users:
            d = row["date_joined__date"]
            if d in series:
                series[d]["signups"] = row["c"]

        biz = (
            Business.objects.filter(created_at__date__gte=start, created_at__date__lte=today)
            .values("created_at__date")
            .annotate(c=Count("id"))
        )
        for row in biz:
            d = row["created_at__date"]
            if d in series:
                series[d]["businesses_created"] = row["c"]

        locks = (
            PlatformBillingProfile.objects.filter(locked_at__date__gte=start, locked_at__date__lte=today)
            .values("locked_at__date")
            .annotate(c=Count("id"))
        )
        for row in locks:
            d = row["locked_at__date"]
            if d in series:
                series[d]["locked_businesses"] = row["c"]

        out = []
        for d in sorted(series.keys()):
            out.append(
                {
                    "date": d,
                    "signups": series[d]["signups"],
                    "businesses_created": series[d]["businesses_created"],
                    "locked_businesses": series[d]["locked_businesses"],
                }
            )

        return Response(out, status=status.HTTP_200_OK)
