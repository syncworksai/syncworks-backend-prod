from datetime import datetime, timedelta

import os
import requests
from django.utils import timezone

from .connection_store import decrypt_credentials, encrypt_credentials, next_sync_iso, update_connection
from .google_calendar_events import import_events as import_google_events
from .microsoft_calendar_events import import_events as import_microsoft_events
from .mail_service import import_microsoft_mail


def _expired(credentials):
    value = credentials.get("expires_at")
    if not value:
        return True
    try:
        expires = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return expires <= timezone.now()
    except ValueError:
        return True


def _refresh(provider, credentials):
    refresh_token = credentials.get("refresh_token")
    if not refresh_token:
        raise RuntimeError("Refresh token missing. Reconnect this account.")
    if provider == "GOOGLE":
        url = "https://oauth2.googleapis.com/token"
        data = {
            "client_id": os.getenv("GOOGLE_CALENDAR_CLIENT_ID"),
            "client_secret": os.getenv("GOOGLE_CALENDAR_CLIENT_SECRET"),
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
    else:
        tenant = (os.getenv("MICROSOFT_CALENDAR_TENANT") or "common").strip()
        url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
        data = {
            "client_id": os.getenv("MICROSOFT_CALENDAR_CLIENT_ID"),
            "client_secret": os.getenv("MICROSOFT_CALENDAR_CLIENT_SECRET"),
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
            "scope": "openid email profile offline_access User.Read Calendars.ReadWrite Mail.Read Mail.Send",
        }
    response = requests.post(url, data=data, timeout=30)
    response.raise_for_status()
    payload = response.json()
    credentials["access_token"] = payload.get("access_token")
    credentials["refresh_token"] = payload.get("refresh_token") or refresh_token
    credentials["expires_at"] = (timezone.now() + timedelta(seconds=max(60, int(payload.get("expires_in") or 3600) - 60))).isoformat()
    credentials["scope"] = payload.get("scope") or credentials.get("scope") or ""
    return credentials


def connection_access_token(user, connection):
    credentials = decrypt_credentials(connection.get("credential_data") or "")
    if not credentials.get("access_token") or _expired(credentials):
        credentials = _refresh(connection.get("provider"), credentials)
        update_connection(user, connection["id"], {"credential_data": encrypt_credentials(credentials)})
    return credentials.get("access_token"), credentials


def sync_connection(user, connection):
    try:
        token, credentials = connection_access_token(user, connection)
        if connection.get("provider") == "GOOGLE":
            imported = import_google_events(user, connection, token)
            mail_result = {"processed": 0, "leads": 0, "pm_messages": 0, "ignored": 0}
        elif connection.get("provider") == "MICROSOFT":
            imported = import_microsoft_events(user, connection, token)
            mail_result = import_microsoft_mail(user, connection, token) if connection.get("mail_enabled") else {"processed": 0, "leads": 0, "pm_messages": 0, "ignored": 0}
        else:
            raise RuntimeError("This calendar provider is not syncable yet.")
        now = timezone.now().isoformat()
        changes = {
            "credential_data": encrypt_credentials(credentials),
            "last_synced_at": now,
            "next_sync_at": next_sync_iso(connection.get("sync_cadence") or "HOURLY"),
            "last_error": "",
        }
        if connection.get("mail_enabled") and connection.get("provider") == "MICROSOFT":
            changes.update({"mail_last_synced_at": now, "mail_last_error": ""})
        update_connection(user, connection["id"], changes)
        return {"ok": True, "imported": imported, "mail": mail_result, "last_synced_at": now}
    except Exception as exc:
        changes = {
            "last_error": str(exc)[:500],
            "next_sync_at": next_sync_iso(connection.get("sync_cadence") or "HOURLY"),
        }
        if connection.get("mail_enabled"):
            changes["mail_last_error"] = str(exc)[:500]
        update_connection(user, connection["id"], changes)
        return {"ok": False, "imported": 0, "mail": {"processed": 0, "leads": 0, "pm_messages": 0, "ignored": 0}, "detail": str(exc)[:500]}
