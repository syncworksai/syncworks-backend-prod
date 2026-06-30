from __future__ import annotations

from django.db import IntegrityError, transaction
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import (
    AutomationExecution,
    AutomationRule,
    OperationalAlert,
    OperationalEvent,
    Ticket,
    TicketRequirement,
)
from user_accounts.serializers.automation import (
    AutomationExecutionSerializer,
    AutomationRuleSerializer,
)
from user_accounts.viewsets.operations import create_alert_for_event
from user_accounts.viewsets.ticket_conversations import _business_context, _visible_tickets


def _matches(rule, ticket=None, event=None):
    config = rule.trigger_config or {}
    if rule.trigger_type == AutomationRule.TriggerType.MANUAL:
        return True
    if rule.trigger_type == AutomationRule.TriggerType.ETA_DELAYED:
        return bool(event and event.event_type == OperationalEvent.EventType.DELAY_REPORTED)
    if rule.trigger_type == AutomationRule.TriggerType.OPERATIONAL_EVENT:
        expected = config.get("event_type")
        return bool(event and (not expected or event.event_type == expected))
    if rule.trigger_type == AutomationRule.TriggerType.TICKET_STATUS:
        expected = config.get("status")
        return bool(ticket and (not expected or ticket.status == expected))
    return False


def _run_action(rule, execution, ticket=None, event=None, actor=None):
    config = rule.action_config or {}

    if rule.action_type == AutomationRule.ActionType.CREATE_EVENT:
        if not ticket:
            raise ValidationError("CREATE_EVENT requires a ticket.")
        created = OperationalEvent.objects.create(
            business=rule.business,
            ticket=ticket,
            event_type=config.get("event_type", OperationalEvent.EventType.CUSTOM),
            visibility=config.get("visibility", OperationalEvent.Visibility.INTERNAL),
            title=config.get("title", rule.name),
            message=config.get("message", ""),
            data={"automation_rule_id": rule.id, **config.get("data", {})},
            created_by=actor,
        )
        return {"event_id": created.id}

    if rule.action_type == AutomationRule.ActionType.CREATE_REQUIREMENT:
        if not ticket:
            raise ValidationError("CREATE_REQUIREMENT requires a ticket.")
        requirement = TicketRequirement.objects.create(
            ticket=ticket,
            requirement_type=config.get(
                "requirement_type",
                TicketRequirement.RequirementType.CUSTOM,
            ),
            title=config.get("title", rule.name),
            description=config.get("description", ""),
            severity=config.get("severity", TicketRequirement.Severity.NORMAL),
            blocks_progress=bool(config.get("blocks_progress", True)),
            metadata={"automation_rule_id": rule.id},
            created_by=actor,
        )
        return {"requirement_id": requirement.id}

    if rule.action_type == AutomationRule.ActionType.CREATE_ALERT:
        if not event:
            if not ticket:
                raise ValidationError("CREATE_ALERT requires an event or ticket.")
            event = OperationalEvent.objects.create(
                business=rule.business,
                ticket=ticket,
                event_type=OperationalEvent.EventType.MESSAGE,
                visibility=config.get("visibility", OperationalEvent.Visibility.BOTH),
                title=config.get("title", rule.name),
                message=config.get("message", ""),
                data={"automation_rule_id": rule.id},
                created_by=actor,
            )
        alert, created = create_alert_for_event(
            event=event,
            audience=config.get("audience", OperationalAlert.Audience.BUSINESS),
            channel=config.get("channel", OperationalAlert.Channel.IN_APP),
            dedupe_suffix=execution.dedupe_key,
        )
        return {"alert_id": alert.id, "created": created}

    if rule.action_type == AutomationRule.ActionType.UPDATE_TICKET_STATUS:
        if not ticket:
            raise ValidationError("UPDATE_TICKET_STATUS requires a ticket.")
        status = config.get("status")
        valid = {choice[0] for choice in Ticket.Status.choices}
        if status not in valid:
            raise ValidationError("Invalid ticket status.")
        ticket.status = status
        ticket.save(update_fields=["status"])
        return {"ticket_id": ticket.id, "status": status}

    return {"custom": config}


def dispatch_event_rules(event, *, actor=None):
    rules = AutomationRule.objects.filter(
        business=event.business,
        is_active=True,
        trigger_type__in=[
            AutomationRule.TriggerType.OPERATIONAL_EVENT,
            AutomationRule.TriggerType.ETA_DELAYED,
        ],
    ).order_by("priority", "id")

    results = []
    for rule in rules:
        execution, created = execute_rule(
            rule,
            ticket=event.ticket,
            event=event,
            actor=actor,
            dedupe_key=f"event:{event.id}:rule:{rule.id}",
        )
        results.append({
            "rule_id": rule.id,
            "execution_id": execution.id,
            "status": execution.status,
            "created": created,
        })
        if (
            rule.stop_processing
            and execution.status == AutomationExecution.Status.SUCCEEDED
        ):
            break
    return results

def execute_rule(rule, *, ticket=None, event=None, actor=None, dedupe_key=None):
    dedupe_key = dedupe_key or (
        f"rule:{rule.id}:ticket:{getattr(ticket, 'id', 0)}:"
        f"event:{getattr(event, 'id', 0)}"
    )
    try:
        with transaction.atomic():
            execution = AutomationExecution.objects.create(
                rule=rule,
                ticket=ticket,
                event=event,
                dedupe_key=dedupe_key,
                executed_by=actor,
            )
    except IntegrityError:
        return AutomationExecution.objects.get(
            rule=rule,
            dedupe_key=dedupe_key,
        ), False

    if not _matches(rule, ticket=ticket, event=event):
        execution.status = AutomationExecution.Status.SKIPPED
        execution.completed_at = timezone.now()
        execution.save(update_fields=["status", "completed_at"])
        return execution, True

    try:
        execution.output_data = _run_action(
            rule,
            execution,
            ticket=ticket,
            event=event,
            actor=actor,
        )
        execution.status = AutomationExecution.Status.SUCCEEDED
    except Exception as exc:
        execution.status = AutomationExecution.Status.FAILED
        execution.error_message = str(exc)

    execution.completed_at = timezone.now()
    execution.save(
        update_fields=[
            "status",
            "output_data",
            "error_message",
            "completed_at",
        ]
    )
    return execution, True


class AutomationRuleListCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        business, _, _ = _business_context(request)
        rows = AutomationRule.objects.filter(business=business)
        return Response(AutomationRuleSerializer(rows, many=True).data)

    def post(self, request):
        business, _, _ = _business_context(request)
        serializer = AutomationRuleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            rule = serializer.save(business=business, created_by=request.user)
        except IntegrityError:
            raise ValidationError({"name": "An automation rule with this name already exists."})
        return Response(AutomationRuleSerializer(rule).data, status=201)


class AutomationRuleDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, rule_id):
        business, _, _ = _business_context(request)
        rule = AutomationRule.objects.filter(id=rule_id, business=business).first()
        if not rule:
            raise Http404
        serializer = AutomationRuleSerializer(rule, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        return Response(AutomationRuleSerializer(serializer.save()).data)


class AutomationExecuteAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, rule_id):
        business, _, _ = _business_context(request)
        rule = AutomationRule.objects.filter(
            id=rule_id,
            business=business,
            is_active=True,
        ).first()
        if not rule:
            raise Http404

        ticket = None
        if request.data.get("ticket"):
            ticket = _visible_tickets(request, "BUSINESS").filter(
                id=request.data["ticket"]
            ).first()
            if not ticket:
                raise ValidationError({"ticket": "Ticket was not found."})

        event = None
        if request.data.get("event"):
            event = OperationalEvent.objects.filter(
                id=request.data["event"],
                business=business,
            ).first()
            if not event:
                raise ValidationError({"event": "Operational event was not found."})
            ticket = ticket or event.ticket

        execution, created = execute_rule(
            rule,
            ticket=ticket,
            event=event,
            actor=request.user,
            dedupe_key=str(request.data.get("dedupe_key") or "") or None,
        )
        return Response(
            {
                "created": created,
                "execution": AutomationExecutionSerializer(execution).data,
            },
            status=201 if created else 200,
        )


class AutomationExecutionListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        business, _, _ = _business_context(request)
        rows = AutomationExecution.objects.filter(
            rule__business=business
        ).select_related("rule", "ticket", "event")
        return Response(AutomationExecutionSerializer(rows[:200], many=True).data)
