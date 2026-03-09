# backend/user_accounts/viewsets/calendar.py
from __future__ import annotations

import os
import secrets
import requests

from django.utils import timezone
from rest_framework import viewsets, mixins
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models import CalendarAccount
from user_accounts.serializers.calendar import CalendarAccountSerializer

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"

MS_AUTH = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MS_TOKEN = "https://login.microsoftonline.com/common/oauth2/v2.0/token"


def _frontend_base() -> str:
    return os.environ.get("FRONTEND_BASE_URL", "http://127.0.0.1:5173").rstrip("/")


class CalendarAccountViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = CalendarAccountSerializer

    def get_queryset(self):
        return CalendarAccount.objects.filter(user=self.request.user).order_by("-created_at")

    @action(detail=False, methods=["post"], url_path="connect/google/begin")
    def google_begin(self, request):
        client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
        if not client_id:
            return Response({"detail": "Missing GOOGLE_OAUTH_CLIENT_ID"}, status=400)

        state = secrets.token_urlsafe(32)
        redirect_uri = f"{_frontend_base()}/customer/settings?provider=google"

        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile https://www.googleapis.com/auth/calendar",
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }

        url = requests.Request("GET", GOOGLE_AUTH, params=params).prepare().url
        return Response({"ok": True, "auth_url": url, "state": state, "redirect_uri": redirect_uri})

    @action(detail=False, methods=["post"], url_path="connect/google/finish")
    def google_finish(self, request):
        code = (request.data or {}).get("code", "")
        redirect_uri = (request.data or {}).get("redirect_uri", f"{_frontend_base()}/customer/settings?provider=google")

        client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
        client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
        if not client_id or not client_secret:
            return Response({"detail": "Missing Google OAuth env vars"}, status=400)

        if not code:
            return Response({"detail": "Missing code"}, status=400)

        r = requests.post(
            GOOGLE_TOKEN,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()

        access = data.get("access_token", "")
        refresh = data.get("refresh_token", "")
        expires_in = int(data.get("expires_in", 3600))
        if not access:
            return Response({"detail": "No access_token returned"}, status=400)

        acct = CalendarAccount.objects.create(
            user=request.user,
            provider="GOOGLE",
            calendar_id="primary",
            is_active=True,
        )
        acct.access_token = access
        if refresh:
            acct.refresh_token = refresh
        acct.token_expires_at = timezone.now() + timezone.timedelta(seconds=expires_in - 60)
        acct.external_account_id = f"google:{request.user.id}:{acct.id}"
        acct.save()

        return Response({"ok": True, "account": CalendarAccountSerializer(acct).data})

    @action(detail=False, methods=["post"], url_path="connect/microsoft/begin")
    def ms_begin(self, request):
        client_id = os.environ.get("MS_OAUTH_CLIENT_ID", "").strip()
        if not client_id:
            return Response({"detail": "Missing MS_OAUTH_CLIENT_ID"}, status=400)

        state = secrets.token_urlsafe(32)
        redirect_uri = f"{_frontend_base()}/customer/settings?provider=microsoft"

        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "response_mode": "query",
            "scope": "offline_access https://graph.microsoft.com/Calendars.ReadWrite openid email profile",
            "state": state,
        }

        url = requests.Request("GET", MS_AUTH, params=params).prepare().url
        return Response({"ok": True, "auth_url": url, "state": state, "redirect_uri": redirect_uri})

    @action(detail=False, methods=["post"], url_path="connect/microsoft/finish")
    def ms_finish(self, request):
        code = (request.data or {}).get("code", "")
        redirect_uri = (request.data or {}).get("redirect_uri", f"{_frontend_base()}/customer/settings?provider=microsoft")

        client_id = os.environ.get("MS_OAUTH_CLIENT_ID", "").strip()
        client_secret = os.environ.get("MS_OAUTH_CLIENT_SECRET", "").strip()
        if not client_id or not client_secret:
            return Response({"detail": "Missing Microsoft OAuth env vars"}, status=400)

        if not code:
            return Response({"detail": "Missing code"}, status=400)

        r = requests.post(
            MS_TOKEN,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "scope": "offline_access https://graph.microsoft.com/Calendars.ReadWrite",
            },
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()

        access = data.get("access_token", "")
        refresh = data.get("refresh_token", "")
        expires_in = int(data.get("expires_in", 3600))
        if not access:
            return Response({"detail": "No access_token returned"}, status=400)

        acct = CalendarAccount.objects.create(
            user=request.user,
            provider="MICROSOFT",
            calendar_id="",
            is_active=True,
        )
        acct.access_token = access
        if refresh:
            acct.refresh_token = refresh
        acct.token_expires_at = timezone.now() + timezone.timedelta(seconds=expires_in - 60)
        acct.external_account_id = f"microsoft:{request.user.id}:{acct.id}"
        acct.save()

        return Response({"ok": True, "account": CalendarAccountSerializer(acct).data})

    @action(detail=True, methods=["post"], url_path="disconnect")
    def disconnect(self, request, pk=None):
        acct = self.get_queryset().filter(pk=pk).first()
        if not acct:
            return Response({"detail": "Not found"}, status=404)
        acct.is_active = False
        acct.save(update_fields=["is_active", "updated_at"])
        return Response({"ok": True})
