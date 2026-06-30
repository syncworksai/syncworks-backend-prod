from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from user_accounts.models import (
    AutomationExecution,
    AutomationRule,
    Business,
    BusinessMember,
    OperationalEvent,
    ServiceCategory,
    Ticket,
    TicketRequirement,
)
from user_accounts.viewsets.operations import TicketEventListCreateAPIView


class AutomationDispatchTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.customer = User.objects.create_user(
            username="dispatch-customer",
            email="dispatch-customer@example.com",
            password="test-pass-123",
        )
        self.owner = User.objects.create_user(
            username="dispatch-owner",
            email="dispatch-owner@example.com",
            password="test-pass-123",
        )
        self.manager = User.objects.create_user(
            username="dispatch-manager",
            email="dispatch-manager@example.com",
            password="test-pass-123",
        )
        self.business = Business.objects.create(
            owner=self.owner,
            name="Dispatch Automation Co",
        )
        BusinessMember.objects.create(
            business=self.business,
            user=self.manager,
            role="MANAGER",
            is_active=True,
        )
        category = ServiceCategory.objects.create(
            key="dispatch-service",
            name="Dispatch Service",
        )
        self.ticket = Ticket.objects.create(
            customer=self.customer,
            assigned_business=self.business,
            assigned_member=self.manager,
            category=category,
            status="IN_PROGRESS",
        )
        self.factory = APIRequestFactory()

    def _post_event(self, event_type):
        request = self.factory.post(
            f"/api/v1/tickets/{self.ticket.id}/events/",
            {
                "event_type": event_type,
                "visibility": "BOTH",
                "title": "Operational update",
                "message": "Automated dispatch test.",
            },
            format="json",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        force_authenticate(request, user=self.manager)
        return TicketEventListCreateAPIView.as_view()(
            request,
            ticket_id=self.ticket.id,
        )

    def test_matching_event_rule_runs_automatically(self):
        AutomationRule.objects.create(
            business=self.business,
            name="Arrival blocker",
            trigger_type="OPERATIONAL_EVENT",
            trigger_config={"event_type": "CREW_ARRIVED"},
            action_type="CREATE_REQUIREMENT",
            action_config={
                "title": "Confirm site access",
                "blocks_progress": True,
            },
        )

        response = self._post_event("CREW_ARRIVED")

        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            TicketRequirement.objects.filter(
                ticket=self.ticket,
                title="Confirm site access",
            ).exists()
        )
        self.assertEqual(
            AutomationExecution.objects.filter(status="SUCCEEDED").count(),
            1,
        )

    def test_nonmatching_rule_is_recorded_as_skipped(self):
        AutomationRule.objects.create(
            business=self.business,
            name="Only delayed",
            trigger_type="OPERATIONAL_EVENT",
            trigger_config={"event_type": "DELAY_REPORTED"},
            action_type="CUSTOM",
        )

        response = self._post_event("CREW_EN_ROUTE")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            AutomationExecution.objects.filter(status="SKIPPED").count(),
            1,
        )

    def test_inactive_rule_does_not_run(self):
        AutomationRule.objects.create(
            business=self.business,
            name="Inactive arrival rule",
            trigger_type="OPERATIONAL_EVENT",
            trigger_config={"event_type": "CREW_ARRIVED"},
            action_type="CREATE_REQUIREMENT",
            action_config={"title": "Should not exist"},
            is_active=False,
        )

        response = self._post_event("CREW_ARRIVED")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(AutomationExecution.objects.count(), 0)

    def test_dispatch_is_deduplicated_per_event_and_rule(self):
        rule = AutomationRule.objects.create(
            business=self.business,
            name="One event one execution",
            trigger_type="OPERATIONAL_EVENT",
            trigger_config={"event_type": "CREW_ARRIVED"},
            action_type="CUSTOM",
        )
        event = OperationalEvent.objects.create(
            business=self.business,
            ticket=self.ticket,
            event_type="CREW_ARRIVED",
            visibility="BOTH",
            title="Crew arrived",
            created_by=self.manager,
        )

        from user_accounts.viewsets.automation import dispatch_event_rules

        first = dispatch_event_rules(event, actor=self.manager)
        second = dispatch_event_rules(event, actor=self.manager)

        self.assertTrue(first[0]["created"])
        self.assertFalse(second[0]["created"])
        self.assertEqual(
            AutomationExecution.objects.filter(rule=rule, event=event).count(),
            1,
        )

    def test_stop_processing_stops_after_success(self):
        AutomationRule.objects.create(
            business=self.business,
            name="First successful rule",
            trigger_type="OPERATIONAL_EVENT",
            trigger_config={"event_type": "CREW_ARRIVED"},
            action_type="CUSTOM",
            priority=1,
            stop_processing=True,
        )
        AutomationRule.objects.create(
            business=self.business,
            name="Second rule",
            trigger_type="OPERATIONAL_EVENT",
            trigger_config={"event_type": "CREW_ARRIVED"},
            action_type="CREATE_REQUIREMENT",
            action_config={"title": "Should never run"},
            priority=2,
        )

        response = self._post_event("CREW_ARRIVED")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(AutomationExecution.objects.count(), 1)
        self.assertFalse(
            TicketRequirement.objects.filter(
                ticket=self.ticket,
                title="Should never run",
            ).exists()
        )
