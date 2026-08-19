from __future__ import annotations

from .assistant_connection_views import _external_mail_state, _personal_ticket_rows


def enrich_daily_state_with_inbox(user, payload):
    """Attach inbox/email intelligence to the existing SYNC daily-state payload."""
    syncworks_rows = _personal_ticket_rows(user)
    external = _external_mail_state(user)

    unread_syncworks = sum(1 for row in syncworks_rows if row.get("unread"))
    attention_syncworks = sum(1 for row in syncworks_rows if row.get("needs_attention"))
    external_unread = int(external.get("unread_count") or 0)
    external_priority = int(external.get("high_priority_count") or 0)
    total_unread = unread_syncworks + external_unread
    total_high_priority = attention_syncworks + external_priority

    inbox = {
        "available": True,
        "syncworks": {
            "unread_count": unread_syncworks,
            "needs_attention_count": attention_syncworks,
            "conversations": syncworks_rows[:10],
        },
        "external_email": external,
        "total_unread": total_unread,
        "total_high_priority": total_high_priority,
        "url": "/customer/inbox",
    }
    payload["inbox"] = inbox

    if total_unread:
        priority = "high" if total_high_priority else "normal"
        item = {
            "category": "inbox",
            "priority": priority,
            "title": f"{total_unread} unread message{'s' if total_unread != 1 else ''}",
            "detail": (
                f"{total_high_priority} conversation{'s' if total_high_priority != 1 else ''} need attention."
                if total_high_priority
                else "You have unread conversations waiting in your connected inbox."
            ),
            "action": {"label": "Open inbox", "url": "/customer/inbox"},
        }
        items = list(payload.get("needs_attention") or [])
        items.append(item)
        order = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
        payload["needs_attention"] = sorted(
            items, key=lambda row: order.get(row.get("priority"), 9)
        )[:8]
        payload["recommended_next"] = payload["needs_attention"][0]

    sections = list(payload.get("briefing_sections") or [])
    if total_unread or external.get("available"):
        details = []
        if unread_syncworks:
            details.append(f"{unread_syncworks} unread SyncWorks conversation{'s' if unread_syncworks != 1 else ''}")
        if external_unread:
            details.append(f"{external_unread} unread email{'s' if external_unread != 1 else ''}")
        if not details:
            details.append("your connected inbox has no unread messages")
        sections.append({
            "id": "inbox",
            "title": "Messages and email",
            "summary": "You have " + " and ".join(details) + ".",
            "details_url": "/customer/inbox",
            "priority": "high" if total_high_priority else "normal",
            "count": total_unread,
        })

    payload["briefing_sections"] = sections
    payload["total_updates"] = len(sections)
    payload["high_priority_count"] = sum(
        1
        for item in payload.get("needs_attention") or []
        if item.get("priority") in {"urgent", "high"}
    )
    return payload
