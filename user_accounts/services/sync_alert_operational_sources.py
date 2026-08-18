from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from platform_growth.models import GrowthContentQueueItem
from user_accounts.models import Notification, OperationalAlert


def _upsert_notification(*, recipient, source, code, severity, title, body, deep_link, dedupe_key, payload=None):
    now = timezone.now()
    data = {
        "sync_alert": True,
        "source": source,
        "code": code,
        "severity": severity,
        "deep_link": deep_link,
        "dedupe_key": dedupe_key,
        "payload": payload or {},
        "last_seen_at": now.isoformat(),
        "push_ready": True,
    }
    existing = Notification.objects.filter(
        recipient=recipient,
        archived_at__isnull=True,
        data__dedupe_key=dedupe_key,
    ).order_by("-created_at").first()
    if existing:
        changed = existing.title != title or existing.body != body or (existing.data or {}).get("severity") != severity
        existing.title = title[:255]
        existing.body = body[:2000]
        existing.data = data
        if changed:
            existing.is_read = False
            existing.read_at = None
            existing.save(update_fields=["title", "body", "data", "is_read", "read_at"])
        else:
            existing.save(update_fields=["data"])
        return False

    Notification.objects.create(
        recipient=recipient,
        type=Notification.TYPE_REMINDER,
        title=title[:255],
        body=body[:2000],
        data=data,
    )
    return True


def sync_social_failure_alerts(*, lookback_hours=72, limit=250):
    cutoff = timezone.now() - timedelta(hours=max(1, int(lookback_hours)))
    rows = (
        GrowthContentQueueItem.objects.filter(
            status=GrowthContentQueueItem.Status.FAILED,
            updated_at__gte=cutoff,
        )
        .select_related("created_by", "draft", "draft__created_by", "channel_connection", "channel_connection__created_by")
        .order_by("-updated_at")[: max(1, int(limit))]
    )
    created = updated = skipped = 0
    for row in rows:
        recipient = row.created_by or row.draft.created_by or row.channel_connection.created_by
        if not recipient or not getattr(recipient, "is_active", False):
            skipped += 1
            continue
        detail = str(row.fail_reason or "The scheduled social post could not be published.").strip()
        provider = str(row.channel_connection.provider or "social").title()
        was_created = _upsert_notification(
            recipient=recipient,
            source="SOCIAL",
            code="SOCIAL_PUBLISH_FAILED",
            severity="HIGH",
            title=f"{provider} post needs attention",
            body=detail,
            deep_link="/sbo/growth",
            dedupe_key=f"SYNC:SOCIAL:SOCIAL_PUBLISH_FAILED:queue-{row.id}",
            payload={"queue_item_id": row.id, "draft_id": row.draft_id, "provider": row.channel_connection.provider},
        )
        created += int(was_created)
        updated += int(not was_created)
    return {"scanned": len(rows), "created": created, "updated": updated, "skipped": skipped}


def sync_operational_alerts(*, lookback_days=14, limit=500):
    cutoff = timezone.now() - timedelta(days=max(1, int(lookback_days)))
    rows = (
        OperationalAlert.objects.filter(
            recipient__isnull=False,
            created_at__gte=cutoff,
            channel=OperationalAlert.Channel.IN_APP,
        )
        .exclude(status=OperationalAlert.Status.SUPPRESSED)
        .select_related("recipient", "event", "event__ticket", "event__business")
        .order_by("-created_at")[: max(1, int(limit))]
    )
    created = updated = skipped = 0
    for alert in rows:
        recipient = alert.recipient
        if not recipient or not getattr(recipient, "is_active", False):
            skipped += 1
            continue
        event = alert.event
        event_type = str(event.event_type or "OPERATIONAL_UPDATE")
        severity = "HIGH" if event_type in {"DELAY_REPORTED", "JOB_BLOCKED"} else "MEDIUM"
        source = "PM" if str(getattr(event.ticket, "source", "") or "").upper().startswith("PM") else "OPERATIONS"
        body = str(event.message or event.title or "A work item has an operational update.").strip()
        was_created = _upsert_notification(
            recipient=recipient,
            source=source,
            code=event_type,
            severity=severity,
            title=str(event.title or "Operational update"),
            body=body,
            deep_link=f"/tickets/{event.ticket_id}",
            dedupe_key=f"SYNC:{source}:{event_type}:operational-alert-{alert.id}",
            payload={"operational_alert_id": alert.id, "event_id": event.id, "ticket_id": event.ticket_id},
        )
        created += int(was_created)
        updated += int(not was_created)
    return {"scanned": len(rows), "created": created, "updated": updated, "skipped": skipped}


def refresh_operational_sync_alerts():
    return {
        "social": sync_social_failure_alerts(),
        "operations": sync_operational_alerts(),
    }
