# backend/user_accounts/services/calendar_sync.py
from __future__ import annotations

import hashlib
import os
import requests
from django.utils import timezone
from django.db import transaction

from user_accounts.models import CalendarAccount, TicketCalendarLink

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_EVENTS_BASE = "https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"

MS_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
MS_EVENTS_BASE = "https://graph.microsoft.com/v1.0/me/events"


def _fingerprint(payload: dict) -> str:
    raw = repr(sorted(payload.items())).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _ticket_to_event_payload(ticket) -> dict:
    """
    Convert your Ticket into a normalized event payload.
    We use scheduled_at if present, otherwise we do NOT sync (no date/time).
    """
    title = ticket.title or ticket.category_name or f"SyncWorks Ticket #{ticket.id}"
    address = getattr(ticket, "service_address", "") or ""
    zipc = getattr(ticket, "service_zip", "") or ""
    location = " ".join([x for x in [address, zipc] if x]).strip()

    # Use scheduled_at as start; default to 1h event
    start_dt = getattr(ticket, "scheduled_at", None)
    if not start_dt:
        return {}

    end_dt = start_dt + timezone.timedelta(hours=1)

    desc_parts = []
    if getattr(ticket, "description", ""):
        desc_parts.append(ticket.description)
    desc_parts.append(f"Ticket #{ticket.id}")
    if getattr(ticket, "service_zip", ""):
        desc_parts.append(f"ZIP: {ticket.service_zip}")
    description = "\n".join([x for x in desc_parts if x])

    return {
        "title": title,
        "location": location,
        "description": description,
        "start": start_dt,
        "end": end_dt,
        "uid": f"syncworks-ticket-{ticket.id}",
    }


def _google_refresh(account: CalendarAccount) -> str:
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise ValueError("Google OAuth env vars missing (GOOGLE_OAUTH_CLIENT_ID/SECRET).")
    if not account.refresh_token:
        raise ValueError("No Google refresh token stored for this account.")

    r = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": account.refresh_token,
        },
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    access = data.get("access_token", "")
    expires_in = int(data.get("expires_in", 3600))
    if not access:
        raise ValueError("Failed to refresh Google access token.")

    account.access_token = access
    account.token_expires_at = timezone.now() + timezone.timedelta(seconds=expires_in - 60)
    account.save(update_fields=["access_token_enc", "token_expires_at", "updated_at"])
    return access


def _ms_refresh(account: CalendarAccount) -> str:
    client_id = os.environ.get("MS_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.environ.get("MS_OAUTH_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise ValueError("Microsoft OAuth env vars missing (MS_OAUTH_CLIENT_ID/SECRET).")
    if not account.refresh_token:
        raise ValueError("No Microsoft refresh token stored for this account.")

    r = requests.post(
        MS_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": account.refresh_token,
            "scope": "offline_access https://graph.microsoft.com/Calendars.ReadWrite",
        },
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    access = data.get("access_token", "")
    expires_in = int(data.get("expires_in", 3600))
    if not access:
        raise ValueError("Failed to refresh Microsoft access token.")

    account.access_token = access
    account.token_expires_at = timezone.now() + timezone.timedelta(seconds=expires_in - 60)
    account.save(update_fields=["access_token_enc", "token_expires_at", "updated_at"])
    return access


def _ensure_access_token(account: CalendarAccount) -> str:
    if account.access_token and not account.is_expired():
        return account.access_token
    if account.provider == "GOOGLE":
        return _google_refresh(account)
    if account.provider == "MICROSOFT":
        return _ms_refresh(account)
    raise ValueError("Unknown provider")


def _google_upsert_event(account: CalendarAccount, link: TicketCalendarLink, payload: dict) -> str:
    access = _ensure_access_token(account)
    headers = {"Authorization": f"Bearer {access}", "Content-Type": "application/json"}

    body = {
        "summary": payload["title"],
        "location": payload["location"],
        "description": payload["description"],
        "start": {"dateTime": payload["start"].isoformat()},
        "end": {"dateTime": payload["end"].isoformat()},
    }

    base = GOOGLE_EVENTS_BASE.format(calendar_id=(account.calendar_id or "primary"))
    if link.external_event_id:
        url = f"{base}/{link.external_event_id}"
        r = requests.put(url, json=body, headers=headers, timeout=20)
        r.raise_for_status()
        return link.external_event_id

    r = requests.post(base, json=body, headers=headers, timeout=20)
    r.raise_for_status()
    data = r.json()
    eid = data.get("id", "")
    if not eid:
        raise ValueError("Google returned no event id.")
    return eid


def _ms_upsert_event(account: CalendarAccount, link: TicketCalendarLink, payload: dict) -> str:
    access = _ensure_access_token(account)
    headers = {"Authorization": f"Bearer {access}", "Content-Type": "application/json"}

    body = {
        "subject": payload["title"],
        "body": {"contentType": "Text", "content": payload["description"]},
        "location": {"displayName": payload["location"]},
        "start": {"dateTime": payload["start"].isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": payload["end"].isoformat(), "timeZone": "UTC"},
    }

    if link.external_event_id:
        url = f"{MS_EVENTS_BASE}/{link.external_event_id}"
        r = requests.patch(url, json=body, headers=headers, timeout=20)
        r.raise_for_status()
        return link.external_event_id

    r = requests.post(MS_EVENTS_BASE, json=body, headers=headers, timeout=20)
    r.raise_for_status()
    data = r.json()
    eid = data.get("id", "")
    if not eid:
        raise ValueError("Microsoft returned no event id.")
    return eid


@transaction.atomic
def sync_ticket_for_user(ticket, user) -> dict:
    """
    Sync ticket to ALL active calendar accounts for this user.
    Returns stats: created/updated
    """
    payload = _ticket_to_event_payload(ticket)
    if not payload:
        return {"ok": False, "detail": "Ticket has no scheduled_at yet."}

    accounts = CalendarAccount.objects.filter(user=user, is_active=True)
    created = 0
    updated = 0

    for acct in accounts:
        link, _ = TicketCalendarLink.objects.get_or_create(
            provider=acct.provider,
            user=user,
            ticket=ticket,
            defaults={"calendar_id": acct.calendar_id or ""},
        )

        fp = _fingerprint(
            {
                "provider": acct.provider,
                "title": payload["title"],
                "location": payload["location"],
                "description": payload["description"],
                "start": payload["start"].isoformat(),
                "end": payload["end"].isoformat(),
            }
        )

        if link.last_synced_fingerprint and link.last_synced_fingerprint == fp:
            continue

        before = bool(link.external_event_id)
        if acct.provider == "GOOGLE":
            eid = _google_upsert_event(acct, link, payload)
            link.external_event_id = eid
            link.calendar_id = acct.calendar_id or "primary"
        elif acct.provider == "MICROSOFT":
            eid = _ms_upsert_event(acct, link, payload)
            link.external_event_id = eid
        else:
            continue

        link.last_synced_at = timezone.now()
        link.last_synced_fingerprint = fp
        link.save()

        if before:
            updated += 1
        else:
            created += 1

    return {"ok": True, "created": created, "updated": updated}
