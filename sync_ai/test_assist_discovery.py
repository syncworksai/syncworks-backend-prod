from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from sync_ai.assist_discovery import discover_pilot_tasks
from user_accounts.models import AuditLog, Business, ServiceRequest, Ticket


class SyncAssistDiscoveryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="assist-discovery", email="jacoblord7@outlook.com", password="testpass123")
        self.other = User.objects.create_user(username="other-discovery", email="other-discovery@example.com", password="testpass123")
        self.business = Business.objects.create(name="Pilot Business", owner=self.owner)
        self.other_business = Business.objects.create(name="Unrelated Business", owner=self.other)

    def test_owner_scoped_new_request_deduplicates_and_preserves_approvals(self):
        request = ServiceRequest.objects.create(customer=self.other, title="Repair", target_business=self.business, status="NEW")
        ServiceRequest.objects.create(customer=self.owner, title="Not ours", target_business=self.other_business, status="NEW")
        self.assertEqual(discover_pilot_tasks(dry_run=True)["created"], 0)
        self.assertEqual(AuditLog.objects.filter(actor=self.owner, action="sync_assist.pilot.task_created").count(), 0)
        first = discover_pilot_tasks()
        second = discover_pilot_tasks()
        self.assertEqual(first["created"], 1)
        self.assertEqual(second["created"], 0)
        events = AuditLog.objects.filter(actor=self.owner, action="sync_assist.pilot.task_created")
        self.assertEqual(events.count(), 1)
        self.assertEqual(events.first().metadata["source_key"], f"service-request:{request.pk}")
        self.assertEqual(events.first().metadata["kind"], "LEAD_FOLLOW_UP")
        self.assertEqual(AuditLog.objects.filter(actor=self.other, action="sync_assist.pilot.task_created").count(), 0)

    def test_ticket_awaiting_approval_is_detected_but_never_executed(self):
        request = ServiceRequest.objects.create(customer=self.owner, title="Test")
        ticket = Ticket.objects.create(customer=self.owner, service_request=request, assigned_business=self.business, work_title="Review repair", status=Ticket.Status.AWAITING_APPROVAL)
        self.assertEqual(discover_pilot_tasks()["created"], 1)
        self.assertEqual(AuditLog.objects.filter(actor=self.owner, action="sync_assist.pilot.task_approved").count(), 0)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.AWAITING_APPROVAL)
