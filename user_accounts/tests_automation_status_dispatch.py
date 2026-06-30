from django.contrib.auth import get_user_model
from django.test import TestCase

from user_accounts.models import (
    AutomationExecution,
    AutomationRule,
    Business,
    ServiceCategory,
    Ticket,
    TicketRequirement,
)
from user_accounts.services.tickets import provider_accept
from user_accounts.viewsets.automation import dispatch_ticket_status_rules


class AutomationStatusDispatchTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.customer = User.objects.create_user(
            username="status-customer",
            email="status-customer@example.com",
            password="test-pass-123",
        )
        self.owner = User.objects.create_user(
            username="status-owner",
            email="status-owner@example.com",
            password="test-pass-123",
        )
        self.business = Business.objects.create(
            owner=self.owner,
            name="Status Automation Co",
        )
        category = ServiceCategory.objects.create(
            key="status-service",
            name="Status Service",
        )
        self.ticket = Ticket.objects.create(
            customer=self.customer,
            assigned_business=self.business,
            category=category,
            status=Ticket.Status.NEW,
        )

    def test_matching_status_rule_runs_after_provider_transition(self):
        AutomationRule.objects.create(
            business=self.business,
            name="Accepted requirement",
            trigger_type="TICKET_STATUS",
            trigger_config={"status": "ACCEPTED"},
            action_type="CREATE_REQUIREMENT",
            action_config={"title": "Schedule customer"},
        )
        provider_accept(self.ticket, self.owner)
        self.assertTrue(
            TicketRequirement.objects.filter(
                ticket=self.ticket,
                title="Schedule customer",
            ).exists()
        )
        self.assertEqual(
            AutomationExecution.objects.filter(status="SUCCEEDED").count(),
            1,
        )

    def test_nonmatching_status_rule_is_skipped(self):
        AutomationRule.objects.create(
            business=self.business,
            name="Completed only",
            trigger_type="TICKET_STATUS",
            trigger_config={"status": "COMPLETED"},
            action_type="CUSTOM",
        )
        provider_accept(self.ticket, self.owner)
        self.assertEqual(
            AutomationExecution.objects.filter(status="SKIPPED").count(),
            1,
        )

    def test_inactive_status_rule_does_not_run(self):
        AutomationRule.objects.create(
            business=self.business,
            name="Inactive accepted rule",
            trigger_type="TICKET_STATUS",
            trigger_config={"status": "ACCEPTED"},
            action_type="CUSTOM",
            is_active=False,
        )
        provider_accept(self.ticket, self.owner)
        self.assertEqual(AutomationExecution.objects.count(), 0)

    def test_status_dispatch_is_deduplicated(self):
        rule = AutomationRule.objects.create(
            business=self.business,
            name="One accepted execution",
            trigger_type="TICKET_STATUS",
            trigger_config={"status": "ACCEPTED"},
            action_type="CUSTOM",
        )
        self.ticket.status = Ticket.Status.ACCEPTED
        self.ticket.save(update_fields=["status"])
        first = dispatch_ticket_status_rules(
            self.ticket,
            actor=self.owner,
            previous_status=Ticket.Status.NEW,
        )
        second = dispatch_ticket_status_rules(
            self.ticket,
            actor=self.owner,
            previous_status=Ticket.Status.NEW,
        )
        self.assertTrue(first[0]["created"])
        self.assertFalse(second[0]["created"])
        self.assertEqual(
            AutomationExecution.objects.filter(rule=rule).count(),
            1,
        )

    def test_stop_processing_stops_later_status_rules(self):
        AutomationRule.objects.create(
            business=self.business,
            name="First accepted rule",
            trigger_type="TICKET_STATUS",
            trigger_config={"status": "ACCEPTED"},
            action_type="CUSTOM",
            priority=1,
            stop_processing=True,
        )
        AutomationRule.objects.create(
            business=self.business,
            name="Second accepted rule",
            trigger_type="TICKET_STATUS",
            trigger_config={"status": "ACCEPTED"},
            action_type="CREATE_REQUIREMENT",
            action_config={"title": "Should not run"},
            priority=2,
        )
        provider_accept(self.ticket, self.owner)
        self.assertEqual(AutomationExecution.objects.count(), 1)
        self.assertFalse(
            TicketRequirement.objects.filter(
                ticket=self.ticket,
                title="Should not run",
            ).exists()
        )
