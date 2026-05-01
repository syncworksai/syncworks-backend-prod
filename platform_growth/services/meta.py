from __future__ import annotations

from django.utils import timezone

from platform_growth.models import (
    PlatformActivationEvent,
    PlatformAutomationRule,
    PlatformConversation,
    PlatformLead,
    PlatformMessage,
)
from platform_growth.services.automation_engine import evaluate_rules


def record_meta_event(payload: dict, event_type: str = "meta.webhook") -> PlatformActivationEvent:
    external_id = str(payload.get("id") or payload.get("object") or "")
    return PlatformActivationEvent.objects.create(
        source="META",
        event_type=event_type,
        external_id=external_id[:180],
        payload=payload,
    )


def _safe_text(value) -> str:
    return str(value or "").strip()


def record_possible_message(change_payload: dict) -> int:
    """
    Best-effort parser for Meta webhook payload fragments.
    Returns number of messages persisted.
    """
    value = change_payload.get("value") if isinstance(change_payload, dict) else None
    if not isinstance(value, dict):
        return 0

    messages = value.get("messages")
    if not isinstance(messages, list):
        return 0

    saved = 0

    for msg in messages:
        if not isinstance(msg, dict):
            continue

        sender_id = _safe_text(msg.get("from"))
        external_message_id = _safe_text(msg.get("id"))
        text = _safe_text((msg.get("text") or {}).get("body") if isinstance(msg.get("text"), dict) else msg.get("text"))

        lead, created = PlatformLead.objects.get_or_create(
            source="META",
            external_id=sender_id,
            defaults={
                "full_name": sender_id,
                "last_activity_at": timezone.now(),
            },
        )

        if created:
            evaluate_rules(
                trigger_type=PlatformAutomationRule.TriggerType.LEAD_CREATED,
                payload={
                    "lead_id": lead.id,
                    "source": lead.source,
                    "external_id": lead.external_id,
                    "full_name": lead.full_name,
                },
                user=None,
            )

        lead.last_activity_at = timezone.now()
        lead.save(update_fields=["last_activity_at", "updated_at"])

        convo, _ = PlatformConversation.objects.get_or_create(
            lead=lead,
            channel=PlatformConversation.Channel.META,
            external_thread_id=sender_id,
            defaults={"status": PlatformConversation.Status.OPEN},
        )

        PlatformMessage.objects.create(
            conversation=convo,
            direction=PlatformMessage.Direction.INBOUND,
            text=text,
            external_message_id=external_message_id,
            raw_payload=msg,
        )

        convo.last_message_at = timezone.now()
        convo.save(update_fields=["last_message_at", "updated_at"])

        saved += 1

    return saved