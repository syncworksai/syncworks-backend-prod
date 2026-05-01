# platform_growth/services/automation_engine.py
from __future__ import annotations

from django.utils import timezone

from platform_growth.models import PlatformActivationEvent, PlatformAutomationExecution, PlatformAutomationRule


SYSTEM_TEMPLATES = [
    {
        "name": "New lead follow-up",
        "description": "Creates a follow-up task recommendation when a lead is created.",
        "trigger_type": PlatformAutomationRule.TriggerType.LEAD_CREATED,
        "action_type": PlatformAutomationRule.ActionType.CREATE_FOLLOW_UP_TASK,
    },
    {
        "name": "Review request",
        "description": "Suggests a review request draft after ticket completion.",
        "trigger_type": PlatformAutomationRule.TriggerType.TICKET_COMPLETED,
        "action_type": PlatformAutomationRule.ActionType.GENERATE_MESSAGE_DRAFT,
    },
    {
        "name": "Win-back campaign",
        "description": "Suggests a social post draft for dormant leads.",
        "trigger_type": PlatformAutomationRule.TriggerType.LEAD_STATUS_CHANGED,
        "action_type": PlatformAutomationRule.ActionType.GENERATE_SOCIAL_POST_DRAFT,
    },
    {
        "name": "Comment-to-DM responder",
        "description": "Logs activation events from inbound comments/messages.",
        "trigger_type": PlatformAutomationRule.TriggerType.INBOUND_MESSAGE_RECEIVED,
        "action_type": PlatformAutomationRule.ActionType.LOG_ACTIVATION_EVENT,
    },
]


def seed_system_templates(user=None):
    for template in SYSTEM_TEMPLATES:
        PlatformAutomationRule.objects.get_or_create(
            name=template["name"],
            defaults={
                **template,
                "status": PlatformAutomationRule.Status.DRAFT,
                "conditions": {},
                "action_config": {},
                "is_system_template": True,
                "created_by": user,
            },
        )


def execute_rule(rule, payload, user=None):
    execution = PlatformAutomationExecution.objects.create(
        rule=rule,
        trigger_type=rule.trigger_type,
        trigger_payload=payload or {},
        status=PlatformAutomationExecution.Status.QUEUED,
    )

    try:
        result = {
            "safe_mode": True,
            "action_type": rule.action_type,
            "message": f"Would execute action '{rule.action_type}' for trigger '{rule.trigger_type}'.",
            "no_outbound_sent": True,
        }

        if rule.action_type == PlatformAutomationRule.ActionType.LOG_ACTIVATION_EVENT:
            event = PlatformActivationEvent.objects.create(
                event_type=f"automation.{rule.trigger_type}",
                source="AUTOMATION_ENGINE",
                payload={
                    "rule_id": rule.id,
                    "rule_name": rule.name,
                    "payload": payload or {},
                },
            )
            result["activation_event_id"] = event.id

        execution.status = PlatformAutomationExecution.Status.COMPLETED
        execution.result = result
        execution.completed_at = timezone.now()
        execution.save(update_fields=["status", "result", "completed_at"])
    except Exception as exc:
        execution.status = PlatformAutomationExecution.Status.FAILED
        execution.error_message = str(exc)
        execution.result = {"safe_mode": True, "no_outbound_sent": True}
        execution.completed_at = timezone.now()
        execution.save(update_fields=["status", "error_message", "result", "completed_at"])

    return execution


def evaluate_rules(trigger_type, payload, user=None):
    rules = PlatformAutomationRule.objects.filter(
        trigger_type=trigger_type,
        status=PlatformAutomationRule.Status.ACTIVE,
    ).order_by("id")

    executions = []
    for rule in rules:
        executions.append(execute_rule(rule, payload=payload, user=user))
    return executions