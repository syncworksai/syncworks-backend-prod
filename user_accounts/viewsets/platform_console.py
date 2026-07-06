# backend/user_accounts/viewsets/platform_console.py
from __future__ import annotations

from datetime import timedelta
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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
DEVELOPER_AGENT_API_BASE = f"https://api.github.com/repos/{DEVELOPER_AGENT_REPOSITORY}"
DEVELOPER_AGENT_ALLOWLIST = {
    "business-growth-backend-persistence-001": "tasks/approved/business-growth-backend-persistence-001.json",
    "god-mode-developer-agent-panel-001": "tasks/approved/god-mode-developer-agent-panel-001.json",
    "business-setup-ui-001": "tasks/approved/business-setup-ui-001.json",
    "developer-agent-smoke-test-001": "tasks/approved/developer-agent-smoke-test-001.json",
    "agent-control-center-foundation-001": "tasks/approved/agent-control-center-foundation-001.json",
}


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


class PlatformDeveloperAgentRunAPIView(APIView):
    permission_classes = [IsAuthenticated, IsGodMode]

    def _token(self):
        return os.environ.get("SYNCWORKS_DEVELOPER_AGENT_TOKEN")

    def _headers(self, token):
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "syncworks-platform-console",
        }

    def _fetch_recent_runs(self, token):
        url = f"{DEVELOPER_AGENT_API_BASE}/actions/workflows/{DEVELOPER_AGENT_WORKFLOW}/runs?event=workflow_dispatch&per_page=10"
        request = Request(url, headers=self._headers(token), method="GET")
        with urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
        return payload.get("workflow_runs") or []

    def post(self, request):
        task_id = (request.data.get("task_id") or "").strip()
        if not task_id or task_id not in DEVELOPER_AGENT_ALLOWLIST:
            return Response({"detail": "Invalid or missing task_id."}, status=status.HTTP_400_BAD_REQUEST)

        token = self._token()
        if not token:
            return Response({"configured": False, "detail": "Developer agent token is not configured."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        task_path = DEVELOPER_AGENT_ALLOWLIST[task_id]

        try:
            recent_runs = self._fetch_recent_runs(token)
            for run in recent_runs:
                if run.get("status") in {"queued", "in_progress"}:
                    return Response(
                        {"detail": "A workflow_dispatch run is already in progress.", "task_id": task_id},
                        status=status.HTTP_409_CONFLICT,
                    )

            dispatch_url = f"{DEVELOPER_AGENT_API_BASE}/actions/workflows/{DEVELOPER_AGENT_WORKFLOW}/dispatches"
            body = json.dumps({"ref": DEVELOPER_AGENT_REF, "inputs": {"task_path": task_path}}).encode("utf-8")
            dispatch_request = Request(dispatch_url, data=body, headers={**self._headers(token), "Content-Type": "application/json"}, method="POST")

            with urlopen(dispatch_request, timeout=10) as response:
                if getattr(response, "status", None) == 204:
                    return Response({"accepted": True, "task_id": task_id}, status=status.HTTP_202_ACCEPTED)
                return Response({"detail": "Unexpected response from GitHub."}, status=status.HTTP_502_BAD_GATEWAY)

        except HTTPError as exc:
            return Response(
                {
                    "detail": "GitHub API request failed.",
                    "status_code": exc.code,
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except URLError:
            return Response({"detail": "Unable to reach GitHub API."}, status=status.HTTP_502_BAD_GATEWAY)
        except json.JSONDecodeError:
            return Response({"detail": "Malformed JSON from GitHub API."}, status=status.HTTP_502_BAD_GATEWAY)
        except Exception:
            return Response({"detail": "Unexpected error while dispatching developer agent task."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PlatformDeveloperAgentStatusAPIView(APIView):
    permission_classes = [IsAuthenticated, IsGodMode]

    def _token(self):
        return os.environ.get("SYNCWORKS_DEVELOPER_AGENT_TOKEN")

    def _headers(self, token):
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "syncworks-platform-console",
        }

    def get(self, request):
        token = self._token()
        configured = bool(token)
        runs = []

        if token:
            try:
                url = f"{DEVELOPER_AGENT_API_BASE}/actions/workflows/{DEVELOPER_AGENT_WORKFLOW}/runs?event=workflow_dispatch&per_page=10"
                req = Request(url, headers=self._headers(token), method="GET")
                with urlopen(req, timeout=10) as response:
                    payload = json.loads(response.read().decode("utf-8") or "{}")
                for run in (payload.get("workflow_runs") or [])[:10]:
                    runs.append(
                        {
                            "id": run.get("id"),
                            "status": run.get("status"),
                            "conclusion": run.get("conclusion"),
                            "created_at": run.get("created_at"),
                            "updated_at": run.get("updated_at"),
                            "html_url": run.get("html_url"),
                            "head_branch": run.get("head_branch"),
                        }
                    )
            except (HTTPError, URLError, json.JSONDecodeError, Exception):
                runs = []

        return Response(
            {
                "configured": configured,
                "repository": DEVELOPER_AGENT_REPOSITORY,
                "workflow": DEVELOPER_AGENT_WORKFLOW,
                "ref": DEVELOPER_AGENT_REF,
                "approved_tasks": DEVELOPER_AGENT_ALLOWLIST,
                "safety_flags": {
                    "branch_only": True,
                    "draft_pr_only": True,
                    "auto_merge": False,
                    "auto_deploy": False,
                    "production_migrations": False,
                },
                "recent_runs": runs,
            },
            status=status.HTTP_200_OK,
        )


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
