from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from datetime import timedelta

from cryptography.fernet import Fernet
from django.conf import settings
from django.utils import timezone

from user_accounts.models import CustomerSettings


PROFILE_KEY = "calendar_connections_v1"


def _fernet() -> Fernet:
    raw = (os.getenv("CALENDAR_TOKEN_ENCRYPTION_KEY") or "").strip()
    if raw:
        try:
            return Fernet(raw.encode("utf-8"))
        except Exception:
            pass
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_credentials(payload: dict) -> str:
    return _fernet().encrypt(json.dumps(payload).encode("utf-8")).decode("utf-8")


def decrypt_credentials(value: str) -> dict:
    if not value:
        return {}
    return json.loads(_fernet().decrypt(value.encode("utf-8")).decode("utf-8"))


def _settings(user):
    obj, _ = CustomerSettings.objects.get_or_create(user=user)
    if not isinstance(obj.finance_profile, dict):
        obj.finance_profile = {}
    return obj


def list_connections(user) -> list[dict]:
    obj = _settings(user)
    rows = obj.finance_profile.get(PROFILE_KEY) or []
    return [dict(row) for row in rows if isinstance(row, dict)]


def save_connections(user, rows: list[dict]) -> list[dict]:
    obj = _settings(user)
    profile = dict(obj.finance_profile or {})
    profile[PROFILE_KEY] = rows
    obj.finance_profile = profile
    obj.save(update_fields=["finance_profile", "updated_at"] if hasattr(obj, "updated_at") else ["finance_profile"])
    return rows


def public_connection(row: dict) -> dict:
    data = {k: v for k, v in row.items() if k != "credential_data"}
    data["connected"] = bool(row.get("credential_data")) and bool(row.get("enabled", True))
    data.setdefault("mail_enabled", False)
    data.setdefault("mail_destinations", [])
    data.setdefault("pm_workspace_ids", [])
    data.setdefault("mail_categories", ["LEADS", "TENANTS", "OWNERS", "MAINTENANCE", "SECTION8", "COLLECTIONS", "VENDORS"])
    data.setdefault("mail_snapshot", {})
    return data


def upsert_connection(user, *, provider: str, external_account_id: str, email: str, display_name: str, credentials: dict, calendars: list[dict]):
    rows = list_connections(user)
    now = timezone.now().isoformat()
    existing = next((r for r in rows if r.get("provider") == provider and r.get("external_account_id") == external_account_id), None)
    if existing is None:
        existing = {
            "id": uuid.uuid4().hex,
            "provider": provider,
            "external_account_id": external_account_id,
            "email": email or "",
            "display_name": display_name or email or provider.title(),
            "sync_mode": "TWO_WAY",
            "sync_cadence": "HOURLY",
            "enabled": True,
            "last_synced_at": None,
            "next_sync_at": now,
            "last_error": "",
            "mail_enabled": False,
            "mail_destinations": [],
            "pm_workspace_ids": [],
            "mail_categories": ["LEADS", "TENANTS", "OWNERS", "MAINTENANCE", "SECTION8", "COLLECTIONS", "VENDORS"],
            "mail_last_synced_at": None,
            "mail_last_error": "",
            "mail_snapshot": {},
            "created_at": now,
        }
        rows.append(existing)
    existing.update({
        "email": email or existing.get("email", ""),
        "display_name": display_name or existing.get("display_name", ""),
        "credential_data": encrypt_credentials(credentials),
        "calendars": calendars,
        "updated_at": now,
        "enabled": True,
        "last_error": "",
    })
    save_connections(user, rows)
    return existing


def find_connection(user, connection_id: str):
    return next((r for r in list_connections(user) if r.get("id") == connection_id), None)


def update_connection(user, connection_id: str, changes: dict):
    allowed = {
        "sync_mode", "sync_cadence", "enabled", "calendars", "last_synced_at", "next_sync_at", "last_error", "credential_data",
        "mail_enabled", "mail_destinations", "pm_workspace_ids", "mail_categories", "mail_last_synced_at", "mail_last_error", "mail_snapshot",
    }
    rows = list_connections(user)
    target = next((r for r in rows if r.get("id") == connection_id), None)
    if target is None:
        return None
    for key, value in changes.items():
        if key in allowed:
            target[key] = value
    target["updated_at"] = timezone.now().isoformat()
    save_connections(user, rows)
    return target


def delete_connection(user, connection_id: str) -> bool:
    rows = list_connections(user)
    kept = [r for r in rows if r.get("id") != connection_id]
    if len(kept) == len(rows):
        return False
    save_connections(user, kept)
    return True


def cadence_delta(cadence: str):
    return {
        "LIVE": timedelta(minutes=1),
        "FIVE_MIN": timedelta(minutes=5),
        "FIFTEEN_MIN": timedelta(minutes=15),
        "HOURLY": timedelta(hours=1),
        "DAILY": timedelta(days=1),
    }.get(cadence)


def next_sync_iso(cadence: str):
    delta = cadence_delta(cadence)
    return (timezone.now() + delta).isoformat() if delta else None
