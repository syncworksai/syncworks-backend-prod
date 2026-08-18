from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.utils import timezone

from sync_ai.calendar_context import build_sync_calendar_context
from sync_ai.health_context import build_sync_health_context
from user_accounts.models import CommunicationPreference, Notification
from user_accounts.services.finance_intelligence import build_finance_briefing


@dataclass(frozen=True)
class AlertCandidate:
    source: str
    code: str
    severity: str
    title: str
    body: str
    deep_link: str
    dedupe_key: str
    payload: dict[str, Any]


SEVERITY_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


def _personal_preference(user) -> CommunicationPreference:
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
    # Django model defaults for TimeField are currently declared as HH:MM strings.
    # Reload so a just-created preference has the same typed datetime.time values as
    # an existing row before quiet-hour comparisons are performed.
    preference.refresh_from_db()
    return preference


def _quiet_hours_active(preference: CommunicationPreference, now=None) -> bool:
    if not preference.quiet_hours_enabled:
        return False
    now = now or timezone.now()
    try:
        local_now = now.astimezone(ZoneInfo(preference.timezone or "America/Chicago"))
    except Exception:
        local_now = timezone.localtime(now)
    current = local_now.time().replace(tzinfo=None)
    start = preference.quiet_hours_start or time(21, 0)
    end = preference.quiet_hours_end or time(7, 0)
    if start == end:
        return True
    if start < end:
        return start <= current < end
    return current >= start or current < end


def _candidate(source, code, severity, title, body, deep_link, *, suffix="", payload=None):
    normalized = str(severity or "MEDIUM").upper()
    if normalized not in SEVERITY_RANK:
        normalized = "MEDIUM"
    key = f"SYNC:{source}:{code}:{suffix or 'ACTIVE'}"[:240]
    return AlertCandidate(
        source=source,
        code=code,
        severity=normalized,
        title=str(title or "SYNC alert")[:255],
        body=str(body or "")[:2000],
        deep_link=deep_link,
        dedupe_key=key,
        payload=payload or {},
    )


def _finance_candidates(user) -> list[AlertCandidate]:
    try:
        briefing = build_finance_briefing(user)
    except Exception:
        return []
    output = []
    for item in briefing.get("alerts") or []:
        code = str(item.get("code") or "FINANCE_ATTENTION")
        output.append(_candidate(
            "FINANCE", code, item.get("severity") or "MEDIUM",
            "Finance needs attention", item.get("message") or "Review your financial command center.",
            "/customer/finance", suffix=code,
        ))
    return output


def _health_candidates(user) -> list[AlertCandidate]:
    try:
        context = build_sync_health_context(user)
    except Exception:
        return []
    if not context.get("available"):
        return []
    output = []
    today = context.get("today") or {}
    local_day = timezone.localdate().isoformat()
    for item in context.get("attention") or []:
        code = str(item.get("code") or "HEALTH_ATTENTION")
        if code == "PROTEIN_REMAINING":
            remaining = item.get("remaining")
            output.append(_candidate("HEALTH", code, "LOW", "Protein remaining", f"You have about {remaining:g}g of protein remaining today.", "/customer/health", suffix=local_day))
        elif code == "STEPS_REMAINING":
            remaining = item.get("remaining")
            output.append(_candidate("HEALTH", code, "LOW", "Steps remaining", f"You have about {remaining:g} steps remaining today.", "/customer/health", suffix=local_day))
        elif code == "WATER_REMAINING":
            remaining = item.get("remaining")
            output.append(_candidate("HEALTH", code, "LOW", "Hydration goal", f"You still have {remaining:g} toward today's water goal.", "/customer/health", suffix=local_day))
        elif code == "SORENESS_RECORDED":
            output.append(_candidate("HEALTH", code, "MEDIUM", "Recovery check", "Soreness is recorded today. Review readiness before training hard.", "/customer/health", suffix=local_day))
    planned = today.get("planned_workout") or {}
    if planned and not today.get("workout_completed"):
        output.append(_candidate("HEALTH", "WORKOUT_INCOMPLETE", "LOW", "Workout still planned", f"{planned.get('workout_name') or 'Your workout'} is still on today's plan.", "/customer/health", suffix=local_day))
    return output


def _calendar_candidates(user) -> list[AlertCandidate]:
    try:
        context = build_sync_calendar_context(user)
    except Exception:
        return []
    output = []
    for item in context.get("attention") or []:
        code = str(item.get("code") or "CALENDAR_ATTENTION")
        event_id = item.get("event_id") or item.get("first_event_id") or ""
        suffix = str(event_id or timezone.localdate().isoformat())
        if code == "CALENDAR_CONFLICT":
            output.append(_candidate("CALENDAR", code, "HIGH", "Calendar conflict", f"SYNC found {item.get('count', 1)} calendar conflict(s).", "/calendar", suffix=suffix))
        elif code == "UPCOMING_EVENT":
            minutes = item.get("minutes_until")
            bucket = minutes // 30 if isinstance(minutes, int) else ""
            output.append(_candidate("CALENDAR", code, "MEDIUM", "Upcoming event", f"{item.get('title') or 'Your next event'} starts in about {minutes} minutes.", "/calendar", suffix=f"{suffix}:{bucket}"))
        elif code in {"TRAVEL_CHANGE", "TRAVEL_ALERT", "WEATHER_RISK"}:
            body = item.get("message") or item.get("detail") or "Travel or weather conditions changed for an upcoming event."
            output.append(_candidate("TRAVEL", code, "HIGH", "Travel plan changed", body, "/calendar", suffix=suffix, payload=item))
    next_event = context.get("next_event") or {}
    travel = next_event.get("travel") or context.get("travel_time") or {}
    alert = travel.get("alert") if isinstance(travel, dict) else None
    if isinstance(alert, dict) and alert.get("message"):
        output.append(_candidate("TRAVEL", "TRAVEL_CHANGE", alert.get("severity") or "HIGH", "Travel plan changed", alert["message"], "/calendar", suffix=str(next_event.get("id") or "next"), payload=alert))
    return output


def collect_personal_alert_candidates(user) -> list[AlertCandidate]:
    candidates = _finance_candidates(user) + _health_candidates(user) + _calendar_candidates(user)
    seen = set()
    output = []
    for candidate in candidates:
        if candidate.dedupe_key in seen:
            continue
        seen.add(candidate.dedupe_key)
        output.append(candidate)
    return sorted(output, key=lambda item: -SEVERITY_RANK[item.severity])


def _should_email(preference, candidate, notification, now=None) -> bool:
    if not preference.email_notifications_enabled or not getattr(notification.recipient, "email", ""):
        return False
    if notification.data.get("email_sent_at"):
        return False
    rank = SEVERITY_RANK.get(candidate.severity, 2)
    if rank < SEVERITY_RANK["HIGH"] and preference.email_digest_for_low_priority:
        return False
    if _quiet_hours_active(preference, now=now) and not (candidate.severity == "CRITICAL" and preference.emergency_override_enabled):
        return False
    return True


def _email_alert(notification, candidate) -> bool:
    try:
        send_mail(
            subject=f"SYNC · {candidate.title}",
            message=f"{candidate.body}\n\nOpen SyncWorks: {candidate.deep_link}",
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[notification.recipient.email],
            fail_silently=False,
        )
        return True
    except Exception:
        return False


def sync_alerts_for_user(user, *, send_email=True, now=None) -> dict[str, int]:
    preference = _personal_preference(user)
    if not preference.automatic_updates_enabled:
        return {"candidates": 0, "created": 0, "updated": 0, "emailed": 0}
    candidates = collect_personal_alert_candidates(user)
    created = updated = emailed = 0
    for candidate in candidates:
        data = {
            "sync_alert": True,
            "source": candidate.source,
            "code": candidate.code,
            "severity": candidate.severity,
            "deep_link": candidate.deep_link,
            "dedupe_key": candidate.dedupe_key,
            "payload": candidate.payload,
            "last_seen_at": (now or timezone.now()).isoformat(),
            "push_ready": bool(preference.push_notifications_enabled),
        }
        existing = Notification.objects.filter(
            recipient=user,
            archived_at__isnull=True,
            data__dedupe_key=candidate.dedupe_key,
        ).order_by("-created_at").first()
        if existing:
            prior_email = (existing.data or {}).get("email_sent_at")
            if prior_email:
                data["email_sent_at"] = prior_email
            changed = existing.title != candidate.title or existing.body != candidate.body or (existing.data or {}).get("severity") != candidate.severity
            existing.title = candidate.title
            existing.body = candidate.body
            existing.data = data
            if changed:
                existing.is_read = False
                existing.read_at = None
                existing.save(update_fields=["title", "body", "data", "is_read", "read_at"])
            else:
                existing.save(update_fields=["data"])
            notification = existing
            updated += 1
        else:
            notification = Notification.objects.create(
                recipient=user,
                type=Notification.TYPE_REMINDER,
                title=candidate.title,
                body=candidate.body,
                data=data,
            )
            created += 1

        if send_email and _should_email(preference, candidate, notification, now=now) and _email_alert(notification, candidate):
            next_data = dict(notification.data or {})
            next_data["email_sent_at"] = (now or timezone.now()).isoformat()
            notification.data = next_data
            notification.save(update_fields=["data"])
            emailed += 1
    return {"candidates": len(candidates), "created": created, "updated": updated, "emailed": emailed}


def refresh_sync_alerts(*, user_limit=250, send_email=True) -> dict[str, int]:
    User = get_user_model()
    totals = {"users": 0, "candidates": 0, "created": 0, "updated": 0, "emailed": 0, "failed": 0}
    users = User.objects.filter(is_active=True).order_by("id")[: max(1, int(user_limit))]
    for user in users:
        try:
            result = sync_alerts_for_user(user, send_email=send_email)
        except Exception:
            totals["failed"] += 1
            continue
        totals["users"] += 1
        for key in ("candidates", "created", "updated", "emailed"):
            totals[key] += result[key]
    return totals
