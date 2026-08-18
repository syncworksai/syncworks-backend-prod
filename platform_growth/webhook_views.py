from __future__ import annotations

from rest_framework import status
from rest_framework.response import Response

from platform_growth.models import PlatformAutomationRule
from platform_growth.services.automation_engine import evaluate_rules
from platform_growth.services.meta import record_meta_event, record_possible_message
from platform_growth.views import MetaWebhookEventAPIView as BaseMetaWebhookEventAPIView


class MetaWebhookEventAPIView(BaseMetaWebhookEventAPIView):
    """Meta webhook parser that preserves the Page/IG entry id for Business attribution."""

    def post(self, request):
        payload = request.data if isinstance(request.data, dict) else {}
        object_name = str(payload.get("object") or "meta")

        created_events = []
        entry_items = payload.get("entry")
        if isinstance(entry_items, list):
            for entry in entry_items:
                if not isinstance(entry, dict):
                    continue

                entry_id = str(entry.get("id") or "").strip()
                event = record_meta_event(entry, event_type=f"meta.{object_name}.entry")
                created_events.append(event.id)

                changes = entry.get("changes")
                if isinstance(changes, list):
                    for idx, change in enumerate(changes):
                        if not isinstance(change, dict):
                            continue

                        record_meta_event(change, event_type=f"meta.{object_name}.change.{idx}")
                        saved_messages = record_possible_message(change, entry_id=entry_id)

                        if saved_messages:
                            evaluate_rules(
                                PlatformAutomationRule.TriggerType.INBOUND_MESSAGE_RECEIVED,
                                payload={"object": object_name, "change": change, "entry_id": entry_id},
                                user=None,
                            )

        if not created_events:
            event = record_meta_event(payload, event_type=f"meta.{object_name}.raw")
            created_events.append(event.id)

        return Response({"ok": True, "event_ids": created_events}, status=status.HTTP_202_ACCEPTED)
