from __future__ import annotations

from .assistant_daily_state import build_daily_state
from .daily_intelligence import enrich_daily_state_with_inbox

_ALLOWED_ATTENTION_CATEGORIES = {
    "calendar",
    "personal_requests",
    "inbox",
    "business",
    "property",
    "weather",
}


def _event(row):
    return {
        "id": row.get("id"),
        "title": row.get("title") or "Calendar item",
        "start_at": row.get("start_at"),
        "end_at": row.get("end_at"),
        "location": row.get("location") or "",
        "address": row.get("address") or "",
        "departure": row.get("departure") or {},
    }


def _conversation(row):
    return {
        "id": row.get("id"),
        "title": row.get("title") or "SyncWorks message",
        "provider": row.get("provider") or "",
        "status": row.get("status") or "",
        "latest_message": row.get("latest_message") or "",
        "latest_message_at": row.get("latest_message_at"),
        "unread": bool(row.get("unread")),
        "needs_attention": bool(row.get("needs_attention")),
    }


def _request(row):
    return {
        "id": row.get("id"),
        "code": row.get("code") or "",
        "title": row.get("title") or "Service request",
        "status": row.get("status") or "",
        "status_label": row.get("status_label") or "",
        "provider": row.get("provider") or "",
        "created_at": row.get("created_at"),
    }


def _attention(row):
    return {
        "category": row.get("category") or "",
        "priority": row.get("priority") or "normal",
        "title": row.get("title") or "SyncWorks update",
        "detail": row.get("detail") or "",
    }


def build_drive_state(user):
    """Return the minimum driver-safe projection of SYNC daily intelligence.

    The full daily-state contains private Finance and Health context. CarPlay never
    receives those sections. This projection is intentionally allow-listed.
    """
    state = enrich_daily_state_with_inbox(user, build_daily_state(user))

    calendar = state.get("calendar") or {}
    inbox = state.get("inbox") or {}
    syncworks_inbox = inbox.get("syncworks") or {}
    personal_requests = state.get("personal_requests") or {}

    attention = [
        _attention(row)
        for row in (state.get("needs_attention") or [])
        if row.get("category") in _ALLOWED_ATTENTION_CATEGORIES
    ][:6]

    return {
        "local_date": state.get("local_date"),
        "generated_at": state.get("generated_at"),
        "events": [_event(row) for row in (calendar.get("events") or [])[:6]],
        "next_event": _event(calendar.get("next_event")) if calendar.get("next_event") else None,
        "messages": [
            _conversation(row)
            for row in (syncworks_inbox.get("conversations") or [])
            if row.get("unread") or row.get("needs_attention")
        ][:6],
        "unread_count": int(inbox.get("total_unread") or 0),
        "requests": [_request(row) for row in (personal_requests.get("items") or [])[:6]],
        "attention": attention,
    }
