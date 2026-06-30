from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from user_accounts.models.business import Business
from user_accounts.models.operations import OperationalEvent
from user_accounts.models.tickets import Ticket


class AutomationRule(models.Model):
    class TriggerType(models.TextChoices):
        OPERATIONAL_EVENT = "OPERATIONAL_EVENT", "Operational Event"
        TICKET_STATUS = "TICKET_STATUS", "Ticket Status"
        ETA_DELAYED = "ETA_DELAYED", "ETA Delayed"
        MANUAL = "MANUAL", "Manual"

    class ActionType(models.TextChoices):
        CREATE_EVENT = "CREATE_EVENT", "Create Event"
        CREATE_REQUIREMENT = "CREATE_REQUIREMENT", "Create Requirement"
        CREATE_ALERT = "CREATE_ALERT", "Create Alert"
        UPDATE_TICKET_STATUS = "UPDATE_TICKET_STATUS", "Update Ticket Status"
        CUSTOM = "CUSTOM", "Custom"

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="automation_rules")
    name = models.CharField(max_length=180)
    trigger_type = models.CharField(max_length=32, choices=TriggerType.choices)
    trigger_config = models.JSONField(default=dict, blank=True)
    action_type = models.CharField(max_length=32, choices=ActionType.choices)
    action_config = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    priority = models.PositiveIntegerField(default=100)
    stop_processing = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="automation_rules_created",
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["priority", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "name"],
                name="ua_automation_rule_name_unique",
            )
        ]
        indexes = [
            models.Index(
                fields=["business", "trigger_type", "is_active"],
                name="ua_auto_rule_trigger_idx",
            )
        ]

    def __str__(self):
        return self.name


class AutomationExecution(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        SKIPPED = "SKIPPED", "Skipped"
        FAILED = "FAILED", "Failed"

    rule = models.ForeignKey(AutomationRule, on_delete=models.CASCADE, related_name="executions")
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="automation_executions",
    )
    event = models.ForeignKey(
        OperationalEvent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="automation_executions",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    dedupe_key = models.CharField(max_length=220)
    input_data = models.JSONField(default=dict, blank=True)
    output_data = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, default="")
    executed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="automation_executions_run",
    )
    created_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["rule", "dedupe_key"],
                name="ua_automation_execution_unique",
            )
        ]
        indexes = [
            models.Index(
                fields=["rule", "status", "created_at"],
                name="ua_auto_exec_status_idx",
            )
        ]

    def __str__(self):
        return f"{self.rule_id}:{self.status}"
