# platform_growth/tests/test_platform_growth_stage10a.py
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from platform_growth.models import PlatformAutomationExecution, PlatformAutomationRule
from platform_growth.services.automation_engine import evaluate_rules

User = get_user_model()


@override_settings(GOD_MODE_EMAIL_ALLOWLIST=["god@example.com"])
class TestPlatformGrowthStage10A(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.god = User.objects.create_user(username="god@example.com", email="god@example.com", password="Password123!")
        self.normal = User.objects.create_user(username="user@example.com", email="user@example.com", password="Password123!")

    def test_can_create_automation_rule_as_god_mode(self):
        self.client.force_authenticate(user=self.god)
        res = self.client.post(
            "/api/v1/platform-growth/automation-rules/",
            {
                "name": "Lead Created Rule",
                "trigger_type": "lead_created",
                "action_type": "generate_message_draft",
                "status": "ACTIVE",
            },
            format="json",
        )
        self.assertEqual(res.status_code, 201)

    def test_non_god_mode_blocked(self):
        self.client.force_authenticate(user=self.normal)
        res = self.client.get("/api/v1/platform-growth/automation-rules/")
        self.assertEqual(res.status_code, 403)

    def test_evaluate_rules_creates_execution_for_active_matching_rule(self):
        rule = PlatformAutomationRule.objects.create(
            name="Active Rule",
            trigger_type="lead_created",
            action_type="generate_message_draft",
            status=PlatformAutomationRule.Status.ACTIVE,
            created_by=self.god,
        )
        executions = evaluate_rules("lead_created", {"lead_id": 1}, user=self.god)
        self.assertEqual(len(executions), 1)
        self.assertEqual(executions[0].rule_id, rule.id)
        self.assertTrue(PlatformAutomationExecution.objects.filter(rule=rule).exists())

    def test_paused_rule_does_not_execute(self):
        PlatformAutomationRule.objects.create(
            name="Paused Rule",
            trigger_type="lead_created",
            action_type="generate_message_draft",
            status=PlatformAutomationRule.Status.PAUSED,
            created_by=self.god,
        )
        executions = evaluate_rules("lead_created", {"lead_id": 2}, user=self.god)
        self.assertEqual(executions, [])
        self.assertEqual(PlatformAutomationExecution.objects.count(), 0)

    def test_no_outbound_api_call_is_made(self):
        rule = PlatformAutomationRule.objects.create(
            name="No Outbound",
            trigger_type="lead_created",
            action_type="generate_social_post_draft",
            status=PlatformAutomationRule.Status.ACTIVE,
            created_by=self.god,
        )
        evaluate_rules("lead_created", {"lead_id": 3}, user=self.god)
        self.assertTrue(PlatformAutomationExecution.objects.filter(rule=rule).exists())
        execution = PlatformAutomationExecution.objects.get(rule=rule)
        self.assertTrue(execution.result.get("no_outbound_sent"))