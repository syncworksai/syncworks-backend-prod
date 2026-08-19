from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.utils import timezone

from user_accounts.models import CommunicationPreference, Notification

from .assistant_daily_state import build_daily_state
from .jarvis_product import load_profile

DEFAULT_PROACTIVE = {
    "enabled": True,
    "morning_briefing": True,
    "morning_time": "07:30",
    "evening_wrap": True,
    "evening_time": "20:30",
    "departure_alerts": True,
    "bill_reminders": True,
    "health_reminders": True,
    "inbox_followups": True,
}

PRIORITY_RANK = {"low": 1, "normal": 2, "high": 3, "urgent": 4, "critical": 4}


def _communication_preference(user):
    preference, _ = CommunicationPreference.objects.get_or_create(
        user=user,
        business=None,
        scope=CommunicationPreference.Scope.PERSONAL,
        defaults={
            "internal_inbox_enabled": True,
            "email_notifications_enabled": True,
            "push_notifications_enabled": True,
            "automatic_updates_enabled": True,
            "urgent_unread_escalation_enabled": True,
            "email_digest_for_low_priority": True,
            "quiet_hours_enabled": True,
            "timezone": "America/Chicago",
        },
    )
    preference.refresh_from_db()
    return preference


def _profile_preferences(user):
    _, profile = load_profile(user)
    modules = profile.get("modules") if isinstance(profile.get("modules"), dict) else {}
    proactive = {**DEFAULT_PROACTIVE, **(modules.get("sync_proactive") or {})}
    devices = modules.get("push_devices") if isinstance(modules.get("push_devices"), list) else []
    devices = [row for row in devices if isinstance(row, dict) and row.get("token") and row.get("active", True)]
    return profile, proactive, devices


def notification_settings_payload(user):
    preference = _communication_preference(user)
    profile, proactive, devices = _profile_preferences(user)
    return {
        "channels": {
            "in_app": True,
            "email": bool(preference.email_notifications_enabled),
            "push": bool(preference.push_notifications_enabled),
            "email_digest_for_low_priority": bool(preference.email_digest_for_low_priority),
        },
        "quiet_hours": {
            "enabled": bool(preference.quiet_hours_enabled),
            "start": preference.quiet_hours_start.strftime("%H:%M") if preference.quiet_hours_start else "21:00",
            "end": preference.quiet_hours_end.strftime("%H:%M") if preference.quiet_hours_end else "07:00",
            "timezone": preference.timezone or profile.get("timezone") or "America/Chicago",
            "emergency_override": bool(preference.emergency_override_enabled),
        },
        "proactive": proactive,
        "push": {
            "registration_ready": True,
            "provider_configured": bool(getattr(settings, "SYNC_PUSH_PROVIDER_CONFIGURED", False)),
            "registered_device_count": len(devices),
            "devices": [
                {
                    "id": row.get("id"),
                    "platform": row.get("platform") or "unknown",
                    "provider": row.get("provider") or "future",
                    "label": row.get("label") or "Device",
                    "registered_at": row.get("registered_at"),
                    "last_seen_at": row.get("last_seen_at"),
                }
                for row in devices
            ],
        },
        "email_sender": getattr(settings, "DEFAULT_FROM_EMAIL", "SyncWorks <no-reply@syncworksapp.com>"),
    }


def _local_now(preference, profile, now=None):
    now = now or timezone.now()
    zone_name = preference.timezone or profile.get("timezone") or "America/Chicago"
    try:
        return now.astimezone(ZoneInfo(zone_name))
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.localtime(now)


def _quiet_hours_active(preference, local_now):
    if not preference.quiet_hours_enabled:
        return False
    current = local_now.time().replace(tzinfo=None)
    start = preference.quiet_hours_start or time(21, 0)
    end = preference.quiet_hours_end or time(7, 0)
    if start == end:
        return True
    if start < end:
        return start <= current < end
    return current >= start or current < end


def _near_clock(local_now, value, window_minutes=35):
    try:
        hour, minute = [int(part) for part in str(value or "").split(":", 1)]
        target = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    except Exception:
        return False
    delta = (local_now - target).total_seconds() / 60
    return 0 <= delta < window_minutes


def _dedupe_exists(user, key):
    return Notification.objects.filter(recipient=user, data__dedupe_key=key).exists()


def _send_email(user, title, body, deep_link):
    if not getattr(user, "email", ""):
        return False
    try:
        base = (getattr(settings, "FRONTEND_URL", "https://syncworksapp.com") or "https://syncworksapp.com").rstrip("/")
        url = f"{base}{deep_link}" if str(deep_link or "").startswith("/") else base
        send_mail(
            subject=f"SYNC by SyncWorks · {title}",
            message=f"{body}\n\nOpen SyncWorks: {url}",
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[user.email],
            fail_silently=False,
        )
        return True
    except Exception:
        return False


def _create_delivery(user, preference, devices, *, title, body, deep_link, source, severity, dedupe_key, email=False, local_now=None):
    if _dedupe_exists(user, dedupe_key):
        return {"created": 0, "emailed": 0}
    push_enabled = bool(preference.push_notifications_enabled)
    push_status = "READY" if push_enabled and devices else "WAITING_FOR_DEVICE" if push_enabled else "DISABLED"
    data = {
        "sync_alert": True,
        "source": source,
        "severity": str(severity or "MEDIUM").upper(),
        "deep_link": deep_link,
        "target_path": deep_link,
        "dedupe_key": dedupe_key,
        "delivery": {
            "in_app": "DELIVERED",
            "email": "PENDING" if email else "DIGEST_OR_DISABLED",
            "push": push_status,
        },
        "push_ready": push_enabled,
        "created_by": "SYNC_NOTIFICATION_ENGINE",
    }
    notification = Notification.objects.create(
        recipient=user,
        type=Notification.TYPE_REMINDER,
        title=title[:255],
        body=body[:2000],
        data=data,
    )
    emailed = 0
    quiet = _quiet_hours_active(preference, local_now or timezone.localtime())
    critical = str(severity or "").lower() in {"urgent", "critical"}
    allow_email = email and preference.email_notifications_enabled and (not quiet or (critical and preference.emergency_override_enabled))
    if allow_email and _send_email(user, title, body, deep_link):
        next_data = dict(notification.data or {})
        delivery = dict(next_data.get("delivery") or {})
        delivery["email"] = "DELIVERED"
        next_data["delivery"] = delivery
        next_data["email_sent_at"] = timezone.now().isoformat()
        notification.data = next_data
        notification.save(update_fields=["data"])
        emailed = 1
    return {"created": 1, "emailed": emailed}


def _category_enabled(category, proactive):
    category = str(category or "").lower()
    if category in {"money", "finance", "billing"}:
        return bool(proactive.get("bill_reminders", True))
    if category == "health":
        return bool(proactive.get("health_reminders", True))
    if category in {"inbox", "messages", "email"}:
        return bool(proactive.get("inbox_followups", True))
    if category in {"calendar", "travel", "weather"}:
        return bool(proactive.get("departure_alerts", True))
    return True


def _attention_deliveries(user, state, preference, proactive, devices, local_now):
    totals = {"created": 0, "emailed": 0}
    local_day = state.get("local_date") or local_now.date().isoformat()
    for item in (state.get("needs_attention") or [])[:8]:
        category = str(item.get("category") or "sync").lower()
        if not _category_enabled(category, proactive):
            continue
        severity = str(item.get("priority") or "normal").lower()
        deep_link = ((item.get("action") or {}).get("url") or "/customer")
        slug = "-".join(str(item.get("title") or "attention").lower().split())[:90]
        dedupe = f"SYNC_NOTIFY:{local_day}:{category}:{slug}"
        rank = PRIORITY_RANK.get(severity, 2)
        email_now = rank >= PRIORITY_RANK["high"] or not preference.email_digest_for_low_priority
        result = _create_delivery(
            user,
            preference,
            devices,
            title=str(item.get("title") or "SYNC needs your attention"),
            body=str(item.get("detail") or "Open SyncWorks to review this item."),
            deep_link=deep_link,
            source=category.upper(),
            severity=severity,
            dedupe_key=dedupe,
            email=email_now,
            local_now=local_now,
        )
        totals["created"] += result["created"]
        totals["emailed"] += result["emailed"]
    return totals


def _briefing_text(state, morning=True):
    attention = state.get("needs_attention") or []
    next_event = (state.get("calendar") or {}).get("next_event") or {}
    unread = int((state.get("inbox") or {}).get("total_unread") or 0)
    pieces = []
    if morning:
        pieces.append(f"You have {len(attention)} item{'s' if len(attention) != 1 else ''} that may need attention today.")
    else:
        pieces.append(f"You have {len(attention)} item{'s' if len(attention) != 1 else ''} still visible in your SYNC action center.")
    if next_event.get("title"):
        pieces.append(f"Next on your calendar: {next_event.get('title')}.")
    if unread:
        pieces.append(f"You have {unread} unread message{'s' if unread != 1 else ''}.")
    if attention:
        pieces.append(f"Top priority: {attention[0].get('title')}.")
    return " ".join(pieces)


def process_user_notifications(user, *, now=None):
    preference = _communication_preference(user)
    if not preference.automatic_updates_enabled:
        return {"created": 0, "emailed": 0, "skipped": 1}
    profile, proactive, devices = _profile_preferences(user)
    if not proactive.get("enabled", True):
        return {"created": 0, "emailed": 0, "skipped": 1}
    local_now = _local_now(preference, profile, now=now)
    state = build_daily_state(user)
    totals = _attention_deliveries(user, state, preference, proactive, devices, local_now)
    local_day = local_now.date().isoformat()

    if proactive.get("morning_briefing", True) and _near_clock(local_now, proactive.get("morning_time") or "07:30"):
        result = _create_delivery(
            user,
            preference,
            devices,
            title="Your morning SYNC briefing",
            body=_briefing_text(state, morning=True),
            deep_link="/customer",
            source="SYNC",
            severity="normal",
            dedupe_key=f"SYNC_NOTIFY:{local_day}:MORNING_BRIEFING",
            email=True,
            local_now=local_now,
        )
        totals["created"] += result["created"]
        totals["emailed"] += result["emailed"]

    if proactive.get("evening_wrap", True) and _near_clock(local_now, proactive.get("evening_time") or "20:30"):
        result = _create_delivery(
            user,
            preference,
            devices,
            title="Your evening SYNC wrap-up",
            body=_briefing_text(state, morning=False),
            deep_link="/customer",
            source="SYNC",
            severity="normal",
            dedupe_key=f"SYNC_NOTIFY:{local_day}:EVENING_WRAP",
            email=True,
            local_now=local_now,
        )
        totals["created"] += result["created"]
        totals["emailed"] += result["emailed"]

    return {**totals, "skipped": 0}


def process_sync_notifications(*, user_limit=500, now=None):
    User = get_user_model()
    totals = {"users": 0, "created": 0, "emailed": 0, "skipped": 0, "failed": 0}
    for user in User.objects.filter(is_active=True).order_by("id")[: max(1, int(user_limit))]:
        try:
            result = process_user_notifications(user, now=now)
        except Exception:
            totals["failed"] += 1
            continue
        totals["users"] += 1
        totals["created"] += result["created"]
        totals["emailed"] += result["emailed"]
        totals["skipped"] += result["skipped"]
    return totals
