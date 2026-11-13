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

    def test_pm_work_order_and_overdue_rent_charge_are_owner_scoped(self):
        from datetime import timedelta
        from decimal import Decimal
        from user_accounts.models import PMProperty, PMUnit, PMTenant, PMRentCharge, PMWorkOrder
        prop = PMProperty.objects.create(business=self.business, name="Test rental")
        unit = PMUnit.objects.create(business=self.business, property=prop, label="1")
        tenant = PMTenant.objects.create(business=self.business, property=prop, unit=unit, first_name="Test")
        PMWorkOrder.objects.create(
            business=self.business, property=prop,
            title="Smoke detector repair", priority=PMWorkOrder.Priority.URGENT,
            status=PMWorkOrder.Status.OPEN,
        )
        PMRentCharge.objects.create(
            business_id=self.business.id, property=prop, unit=unit, tenant=tenant,
            due_date=timezone.localdate() - timedelta(days=3),
            charge_type=PMRentCharge.ChargeType.RENT,
            amount=Decimal("100.00"), balance=Decimal("75.00"),
            status=PMRentCharge.Status.PARTIAL,
        )
        result = discover_pilot_tasks()
        self.assertEqual(result["checked"]["pm_work_orders"], 1)
        self.assertEqual(result["checked"]["pm_rent_charges"], 1)
        self.assertEqual(result["created"], 2)
        self.assertEqual(discover_pilot_tasks()["created"], 0)
        self.assertEqual(PMWorkOrder.objects.filter(business=self.business, status=PMWorkOrder.Status.OPEN).count(), 1)
        self.assertEqual(PMRentCharge.objects.filter(business_id=self.business.id, status=PMRentCharge.Status.PARTIAL).count(), 1)
