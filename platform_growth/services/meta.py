from __future__ import annotations

from django.utils import timezone

from platform_growth.models import (
    GrowthChannelConnection,
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


def _connection_for_entry(entry_id: str | None):
    value = _safe_text(entry_id)
    if not value:
        return None
    return (
        GrowthChannelConnection.objects.filter(
            external_account_id=value,
            status=GrowthChannelConnection.Status.CONNECTED,
        )
        .select_related("created_by")
        .order_by("id")
        .first()
    )


def _referral_metadata(msg: dict, value: dict) -> dict:
    candidates = []
    for source in (msg.get("referral"), value.get("referral"), msg.get("context"), value.get("context")):
        if isinstance(source, dict):
            candidates.append(source)

    result = {}
    for source in candidates:
        for key, target in (
            ("post_id", "source_post_id"),
            ("source_post_id", "source_post_id"),
            ("media_id", "source_post_id"),
            ("ad_id", "source_ad_id"),
            ("ref", "source_ref"),
            ("source", "referral_source"),
            ("type", "referral_type"),
        ):
            if target not in result:
                candidate = _safe_text(source.get(key))
                if candidate:
                    result[target] = candidate[:255]
    return result


def record_possible_message(change_payload: dict, *, entry_id: str | None = None) -> int:
    """Best-effort Meta message parser with Business ownership attribution."""
    value = change_payload.get("value") if isinstance(change_payload, dict) else None
    if not isinstance(value, dict):
        return 0

    messages = value.get("messages")
    if not isinstance(messages, list):
        return 0

    connection = _connection_for_entry(entry_id)
    owner = getattr(connection, "created_by", None)
    saved = 0

    for msg in messages:
        if not isinstance(msg, dict):
            continue

        sender_id = _safe_text(msg.get("from"))
        external_message_id = _safe_text(msg.get("id"))
        if not sender_id:
            continue
        text = _safe_text((msg.get("text") or {}).get("body") if isinstance(msg.get("text"), dict) else msg.get("text"))

        lead_qs = PlatformLead.objects.filter(source="META", external_id=sender_id)
        if owner is not None:
            lead_qs = lead_qs.filter(assigned_to=owner)
        else:
            lead_qs = lead_qs.filter(assigned_to__isnull=True)
        lead = lead_qs.order_by("id").first()
        created = lead is None
        if lead is None:
            lead = PlatformLead.objects.create(
                source="META",
                external_id=sender_id,
                full_name=sender_id,
                last_activity_at=timezone.now(),
                assigned_to=owner,
            )

        metadata = dict(lead.metadata or {})
        if connection is not None:
            metadata.update(
                {
                    "social_connection_id": connection.id,
                    "social_account_id": connection.external_account_id,
                    "social_provider": connection.provider,
                }
            )
        metadata.update(_referral_metadata(msg, value))
        lead.metadata = metadata
        lead.last_activity_at = timezone.now()
        update_fields = ["metadata", "last_activity_at", "updated_at"]
        if owner is not None and lead.assigned_to_id is None:
            lead.assigned_to = owner
            update_fields.append("assigned_to")
        lead.save(update_fields=update_fields)

        if created:
            evaluate_rules(
                trigger_type=PlatformAutomationRule.TriggerType.LEAD_CREATED,
                payload={
                    "lead_id": lead.id,
                    "source": lead.source,
                    "external_id": lead.external_id,
                    "full_name": lead.full_name,
                    "social_connection_id": metadata.get("social_connection_id"),
                    "source_post_id": metadata.get("source_post_id"),
                },
                user=owner,
            )

        convo, _ = PlatformConversation.objects.get_or_create(
            lead=lead,
            channel=PlatformConversation.Channel.META,
            external_thread_id=sender_id,
            defaults={"status": PlatformConversation.Status.OPEN},
        )

        if external_message_id and PlatformMessage.objects.filter(external_message_id=external_message_id).exists():
            continue

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
