# user_accounts/services/notifications.py
from __future__ import annotations

from typing import Optional

from django.utils import timezone

from user_accounts.models import Notification, AuditLog


def notify(
    recipient,
    title: str,
    body: str = "",
    data: dict | None = None,
    *,
    actor=None,
    type: str = Notification.TYPE_SYSTEM,
) -> Notification:
    """
    Create an in-app notification.

    Your Notification model uses:
      - recipient (FK User)
      - actor (optional FK User)
      - type (SYSTEM/BROADCAST/TICKET/BILLING)
      - title/body/data
    """
    n = Notification.objects.create(
        recipient=recipient,
        actor=actor,
        type=type,
        title=title or "",
        body=body or "",
        data=data or {},
    )

    # Optional: lightweight audit log if you want it
    # (Keeps your existing AuditLog model useful; safe no-op if you later remove it)
    try:
        AuditLog.objects.create(
            actor=actor,
            action="NOTIFY",
            message=title or "Notification",
            data={
                "recipient_id": getattr(recipient, "id", None),
                "type": type,
                "title": title,
                "body": body,
                "data": data or {},
            },
            created_at=timezone.now(),
        )
    except Exception:
        # Don't let audit issues block core app flows.
        pass

    return n
