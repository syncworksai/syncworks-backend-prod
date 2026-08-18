from __future__ import annotations

from datetime import timedelta
import os

from django.contrib.auth import get_user_model
from django.core import signing
from django.http import HttpResponseRedirect
from django.utils import timezone
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import google_calendar_oauth as google
from . import microsoft_calendar_oauth as microsoft
from .connection_store import (
    delete_connection,
    find_connection,
    list_connections,
    next_sync_iso,
    public_connection,
    update_connection,
    upsert_connection,
)
from .sync_service import sync_connection

User = get_user_model()
STATE_SALT = "syncworks.calendar.oauth"
ALLOWED_CADENCES = {"LIVE", "FIVE_MIN", "FIFTEEN_MIN", "HOURLY", "DAILY", "MANUAL"}


def _state(user, provider, return_to):
    return signing.dumps({"user_id": str(user.id), "provider": provider, "return_to": return_to}, salt=STATE_SALT)


def _read_state(value):
    return signing.loads(value, salt=STATE_SALT, max_age=900)


def _frontend_redirect(return_to, result, provider):
    base = (os.getenv("FRONTEND_URL") or "https://syncworksapp.com").rstrip("/")
    safe = return_to if str(return_to).startswith("/") else "/customer/settings"
    joiner = "&" if "?" in safe else "?"
    return f"{base}{safe}{joiner}calendar_oauth={result}&provider={provider.lower()}"


def _normalize_calendars(provider, rows):
    output = []
    for row in rows:
        if provider == "GOOGLE":
            calendar_id = row.get("id")
            if not calendar_id:
                continue
            output.append({
                "id": calendar_id,
                "name": row.get("summary") or "Calendar",
                "timezone": row.get("timeZone") or "",
                "color": row.get("backgroundColor") or "",
                "primary": bool(row.get("primary")),
                "selected": bool(row.get("selected", True)),
            })
        else:
            calendar_id = row.get("id")
            if not calendar_id:
                continue
            output.append({
                "id": calendar_id,
                "name": row.get("name") or "Calendar",
                "timezone": "",
                "color": row.get("color") or "",
                "primary": bool(row.get("isDefaultCalendar")),
                "selected": True,
            })
    return output


class CalendarConnectionListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            "connections": [public_connection(row) for row in list_connections(request.user)],
            "providers": {
                "google": bool(os.getenv("GOOGLE_CALENDAR_CLIENT_ID")),
                "microsoft": bool(os.getenv("MICROSOFT_CALENDAR_CLIENT_ID")),
                "apple": False,
            },
        })


class CalendarOAuthStartView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        provider = str(request.data.get("provider") or "").upper()
        return_to = str(request.data.get("return_to") or "/customer/settings")
        if provider not in {"GOOGLE", "MICROSOFT"}:
            return Response({"detail": "This calendar provider is not available yet."}, status=400)
        state = _state(request.user, provider, return_to)
        try:
            url = google.authorization_url(state) if provider == "GOOGLE" else microsoft.authorization_url(state)
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=503)
        return Response({"authorization_url": url})


class CalendarOAuthCallbackView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    provider = ""

    def get(self, request):
        state_value = request.query_params.get("state") or ""
        code = request.query_params.get("code") or ""
        if not state_value or not code:
            return Response({"detail": "Missing OAuth response."}, status=400)
        try:
            state = _read_state(state_value)
            provider = self.provider
            if state.get("provider") != provider:
                raise RuntimeError("OAuth provider state mismatch.")
            user = User.objects.get(id=state["user_id"])
            helper = google if provider == "GOOGLE" else microsoft
            tokens = helper.exchange_code(code)
            access_token = tokens.get("access_token")
            if not access_token:
                raise RuntimeError("Provider did not return an access token.")
            profile = helper.profile(access_token)
            calendars = _normalize_calendars(provider, helper.calendars(access_token))
            expires_in = int(tokens.get("expires_in") or 3600)
            credentials = {
                "access_token": access_token,
                "refresh_token": tokens.get("refresh_token") or "",
                "expires_at": (timezone.now() + timedelta(seconds=max(60, expires_in - 60))).isoformat(),
                "scope": tokens.get("scope") or "",
            }
            connection = upsert_connection(
                user,
                provider=provider,
                external_account_id=str(profile.get("id") or profile.get("email") or "unknown"),
                email=profile.get("email") or "",
                display_name=profile.get("name") or profile.get("email") or provider.title(),
                credentials=credentials,
                calendars=calendars,
            )
            update_connection(user, connection["id"], {"next_sync_at": timezone.now().isoformat()})
            return HttpResponseRedirect(_frontend_redirect(state.get("return_to"), "connected", provider))
        except Exception:
            return HttpResponseRedirect(_frontend_redirect("/customer/settings", "error", self.provider))


class GoogleCalendarOAuthCallbackView(CalendarOAuthCallbackView):
    provider = "GOOGLE"


class MicrosoftCalendarOAuthCallbackView(CalendarOAuthCallbackView):
    provider = "MICROSOFT"


class CalendarConnectionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, connection_id):
        connection = find_connection(request.user, connection_id)
        if not connection:
            return Response({"detail": "Calendar connection not found."}, status=404)
        changes = {}
        if "enabled" in request.data:
            changes["enabled"] = bool(request.data.get("enabled"))
        cadence = str(request.data.get("sync_cadence") or "").upper()
        if cadence:
            if cadence not in ALLOWED_CADENCES:
                return Response({"detail": "Invalid sync cadence."}, status=400)
            changes["sync_cadence"] = cadence
            changes["next_sync_at"] = next_sync_iso(cadence)
        if "calendars" in request.data and isinstance(request.data.get("calendars"), list):
            allowed_ids = {str(row.get("id")) for row in connection.get("calendars") or []}
            calendars = []
            for row in request.data["calendars"]:
                if str(row.get("id")) not in allowed_ids:
                    continue
                original = next((item for item in connection.get("calendars") or [] if str(item.get("id")) == str(row.get("id"))), {})
                merged = dict(original)
                merged["selected"] = bool(row.get("selected", original.get("selected", True)))
                calendars.append(merged)
            changes["calendars"] = calendars
        updated = update_connection(request.user, connection_id, changes)
        return Response(public_connection(updated))

    def delete(self, request, connection_id):
        if not delete_connection(request.user, connection_id):
            return Response({"detail": "Calendar connection not found."}, status=404)
        return Response(status=204)


class CalendarConnectionSyncView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, connection_id):
        connection = find_connection(request.user, connection_id)
        if not connection:
            return Response({"detail": "Calendar connection not found."}, status=404)
        return Response(sync_connection(request.user, connection))
