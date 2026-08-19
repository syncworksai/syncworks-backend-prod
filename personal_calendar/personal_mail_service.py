from __future__ import annotations

from datetime import timezone as dt_timezone

import requests
from django.utils import timezone
from django.utils.dateparse import parse_datetime


def _received(value):
    parsed = parse_datetime(str(value or ""))
    if not parsed:
        return timezone.now()
    return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed, dt_timezone.utc)


def _sender(remote):
    address = ((remote.get("from") or {}).get("emailAddress") or {})
    return {
        "name": str(address.get("name") or "").strip(),
        "email": str(address.get("address") or "").strip().lower(),
    }


def _priority(remote):
    importance = str(remote.get("importance") or "normal").lower()
    subject = str(remote.get("subject") or "").lower()
    preview = str(remote.get("bodyPreview") or "").lower()
    text = f"{subject} {preview}"
    urgent_terms = (
        "urgent", "action required", "past due", "payment due", "final notice",
        "appointment", "rescheduled", "cancelled", "canceled", "deadline",
        "school", "daycare", "doctor", "medical", "insurance",
    )
    if importance == "high" or any(term in text for term in urgent_terms):
        return "high"
    return "normal"


def fetch_microsoft_personal_snapshot(connection, access_token, limit=35):
    response = requests.get(
        "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages",
        headers={"Authorization": f"Bearer {access_token}"},
        params={
            "$top": max(1, min(int(limit or 35), 50)),
            "$orderby": "receivedDateTime desc",
            "$select": "id,conversationId,subject,from,receivedDateTime,bodyPreview,webLink,isRead,importance,hasAttachments",
        },
        timeout=45,
    )
    response.raise_for_status()
    rows = []
    for remote in response.json().get("value") or []:
        sender = _sender(remote)
        rows.append({
            "id": str(remote.get("id") or ""),
            "thread_id": str(remote.get("conversationId") or ""),
            "subject": str(remote.get("subject") or "(No subject)")[:240],
            "sender_name": sender["name"],
            "sender_email": sender["email"],
            "received_at": _received(remote.get("receivedDateTime")).isoformat(),
            "preview": str(remote.get("bodyPreview") or "").strip()[:320],
            "web_link": str(remote.get("webLink") or ""),
            "is_read": bool(remote.get("isRead")),
            "importance": str(remote.get("importance") or "normal"),
            "priority": _priority(remote),
            "has_attachments": bool(remote.get("hasAttachments")),
        })
    unread = sum(1 for row in rows if not row["is_read"])
    high = sum(1 for row in rows if row["priority"] == "high")
    return {
        "provider": "MICROSOFT",
        "mailbox": connection.get("email") or "",
        "captured_at": timezone.now().isoformat(),
        "message_count": len(rows),
        "unread_count": unread,
        "high_priority_count": high,
        "messages": rows,
    }
