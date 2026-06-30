from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from user_accounts.models import (
    AutomationExecution,
    AutomationRule,
    Business,
    BusinessMember,
    OperationalAlert,
    OperationalEvent,
    ServiceCategory,
    Ticket,
    TicketRequirement,
)
from user_accounts.viewsets.automation import (
    AutomationExecuteAPIView,
    AutomationRuleListCreateAPIView,
)


class AutomationRuleTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.customer = User.objects.create_user(
            username="auto-customer",
            email="auto-customer@example.com",
            password="test-pass-123",
        )
        self.owner = User.objects.create_user(
            username="auto-owner",
            email="auto-owner@example.com",
            password="test-pass-123",
        )
        self.employee = User.objects.create_user(
            username="auto-employee",
            email="auto-employee@example.com",
            password="test-pass-123",
        )
        self.business = Business.objects.create(
            owner=self.owner,
            name="Automation Operations Co",
        )
        BusinessMember.objects.create(
            business=self.business,
            user=self.employee,
            role="MANAGER",
            is_active=True,
        )
        category = ServiceCategory.objects.create(
            key="automation-service",
            name="Automation Service",
        )
        self.ticket = Ticket.objects.create(
            customer=self.customer,
            assigned_business=self.business,
            assigned_member=self.employee,
            category=category,
            status="IN_PROGRESS",
        )
        self.factory = APIRequestFactory()

    def _auth(self, request):
        force_authenticate(request, user=self.employee)
        return request

    def test_create_rule(self):
        request = self.factory.post(
            "/api/v1/automation/rules/",
            {
                "name": "Delay creates blocker",
                "trigger_type": "ETA_DELAYED",
                "action_type": "CREATE_REQUIREMENT",
                "action_config": {
                    "title": "Confirm revised arrival",
                    "blocks_progress": True,
                },
            },
            format="json",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        response = AutomationRuleListCreateAPIView.as_view()(self._auth(request))
        self.assertEqual(response.status_code, 201)

    def test_matching_event_creates_requirement(self):
        rule = AutomationRule.objects.create(
            business=self.business,
            name="Delay follow-up",
            trigger_type="OPERATIONAL_EVENT",
            trigger_config={"event_type": "DELAY_REPORTED"},
            action_type="CREATE_REQUIREMENT",
            action_config={"title": "Confirm customer received delay notice"},
        )
        event = OperationalEvent.objects.create(
            business=self.business,
            ticket=self.ticket,
            event_type="DELAY_REPORTED",
            visibility="BOTH",
            title="Arrival delayed",
        )
        request = self.factory.post(
            f"/api/v1/automation/rules/{rule.id}/execute/",
            {"event": event.id},
            format="json",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        response = AutomationExecuteAPIView.as_view()(
            self._auth(request),
            rule_id=rule.id,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["execution"]["status"], "SUCCEEDED")
        self.assertTrue(
            TicketRequirement.objects.filter(
                ticket=self.ticket,
                title="Confirm customer received delay notice",
            ).exists()
        )

    def test_nonmatching_event_is_skipped(self):
        rule = AutomationRule.objects.create(
            business=self.business,
            name="Only job ready",
            trigger_type="OPERATIONAL_EVENT",
            trigger_config={"event_type": "JOB_READY"},
            action_type="CUSTOM",
        )
        event = OperationalEvent.objects.create(
            business=self.business,
            ticket=self.ticket,
            event_type="CREW_EN_ROUTE",
            visibility="BOTH",
            title="Crew en route",
        )
        request = self.factory.post(
            f"/api/v1/automation/rules/{rule.id}/execute/",
            {"event": event.id},
            format="json",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        response = AutomationExecuteAPIView.as_view()(
            self._auth(request),
            rule_id=rule.id,
        )
        self.assertEqual(response.data["execution"]["status"], "SKIPPED")

    def test_duplicate_execution_is_deduplicated(self):
        rule = AutomationRule.objects.create(
            business=self.business,
            name="One-time status update",
            trigger_type="MANUAL",
            action_type="UPDATE_TICKET_STATUS",
            action_config={"status": "AWAITING_APPROVAL"},
        )
        payload = {"ticket": self.ticket.id, "dedupe_key": "ticket-status-once"}
        first = self.factory.post(
            f"/api/v1/automation/rules/{rule.id}/execute/",
            payload,
            format="json",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        second = self.factory.post(
            f"/api/v1/automation/rules/{rule.id}/execute/",
            payload,
            format="json",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        first_response = AutomationExecuteAPIView.as_view()(
            self._auth(first),
            rule_id=rule.id,
        )
        second_response = AutomationExecuteAPIView.as_view()(
            self._auth(second),
            rule_id=rule.id,
        )
        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(AutomationExecution.objects.count(), 1)

    def test_alert_action_creates_customer_alert(self):
        rule = AutomationRule.objects.create(
            business=self.business,
            name="Tell customer job is ready",
            trigger_type="MANUAL",
            action_type="CREATE_ALERT",
            action_config={
                "audience": "CUSTOMER",
                "channel": "IN_APP",
                "title": "Job ready",
                "message": "Your job is ready to continue.",
            },
        )
        request = self.factory.post(
            f"/api/v1/automation/rules/{rule.id}/execute/",
            {"ticket": self.ticket.id},
            format="json",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        response = AutomationExecuteAPIView.as_view()(
            self._auth(request),
            rule_id=rule.id,
        )
        self.assertEqual(response.data["execution"]["status"], "SUCCEEDED")
        self.assertEqual(
            OperationalAlert.objects.filter(recipient=self.customer).count(),
            1,
        )
