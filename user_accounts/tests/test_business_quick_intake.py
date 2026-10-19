from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from user_accounts.models import (
    AuditLog, Business, BusinessCustomer, BusinessMember, Ticket,
    TicketOperationalProfile, User, WorkforceProfile,
)


class BusinessQuickIntakeTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="biz-owner", email="owner@test.com", password="TestPass123!"
        )
        self.dispatcher = User.objects.create_user(
            username="dispatch", email="dispatch@test.com", password="TestPass123!"
        )
        self.tech = User.objects.create_user(
            username="tech", email="tech@test.com", password="TestPass123!"
        )
        self.stranger = User.objects.create_user(
            username="stranger", email="stranger@test.com", password="TestPass123!"
        )
        self.founder = User.objects.create_user(
            username="founder", email="jacoblord7@outlook.com", password="TestPass123!"
        )
        self.business = Business.objects.create(name="Electrical Test", owner=self.owner)
        self.dispatch_member = BusinessMember.objects.create(
            business=self.business, user=self.dispatcher,
            role="DISPATCH", can_assign_tickets=True, can_manage_schedule=True,
        )
        self.tech_member = BusinessMember.objects.create(
            business=self.business, user=self.tech, role="TECHNICIAN"
        )
        WorkforceProfile.objects.create(
            member=self.tech_member, skills=["breaker"], is_schedulable=True
        )
        self.client = APIClient()
        self.client.force_authenticate(self.dispatcher)
        self.path = "/api/v1/business/quick-intake/"
        self.headers = {"HTTP_X_BUSINESS_ID": str(self.business.id)}

    def test_dispatcher_can_create_shared_customer_ticket_and_schedule(self):
        begin = timezone.now() + timedelta(hours=3)
        payload = {
            "customer_name": "Jane Customer", "phone": "(334) 555-0133",
            "email": "JANE@EXAMPLE.COM", "service_label": "Breaker reset",
            "description": "Breaker trips", "service_address": "123 Main St",
            "required_skills": ["breaker"], "assigned_member_id": self.tech.pk,
            "scheduled_start": begin.isoformat(), "estimated_duration_minutes": 45,
        }
        response = self.client.post(self.path, payload, format="json", **self.headers)
        self.assertEqual(response.status_code, 201, response.data)
        ticket = Ticket.objects.get(pk=response.data["ticket_id"])
        self.assertEqual(ticket.assigned_business_id, self.business.pk)
        self.assertEqual(ticket.assigned_member_id, self.tech.pk)
        self.assertEqual(ticket.customer_id, self.owner.pk) # internal placeholder
        self.assertFalse(ticket.customer_visible)
        self.assertEqual(ticket.status, "SCHEDULED")
        self.assertEqual(ticket.operations_profile.required_skills, ["breaker"])
        self.assertEqual(ticket.business_customer.name, "Jane Customer")
        self.assertEqual(ticket.business_customer.ticket_count, 1)
        self.assertEqual(response.data["customer_invited"], False)
        second = self.client.post(
            self.path, {**payload, "service_label": "Another breaker"},
            format="json", **self.headers
        )
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(BusinessCustomer.objects.filter(business=self.business).count(), 1)
        self.assertEqual(BusinessCustomer.objects.get(business=self.business).ticket_count, 2)
        self.assertEqual(Ticket.objects.filter(assigned_business=self.business).count(), 2)
        self.assertTrue(AuditLog.objects.filter(action="business.phone_ticket_created").exists())

    def test_cannot_assign_unqualified_technician(self):
        result = self.client.post(
            self.path, {
                "phone": "3345559999", "service_label": "Breaker",
                "required_skills": ["generator"],
                "assigned_member_id": self.tech.pk
            }, format="json", **self.headers
        )
        self.assertEqual(result.status_code, 400, result.data)
        self.assertEqual(Ticket.objects.count(), 0)
        self.assertEqual(BusinessCustomer.objects.count(), 0)

    def test_stranger_and_tech_cannot_create_or_read_admin_board(self):
        data = {"phone": "3345551010", "service_label": "Outlet"}
        self.client.force_authenticate(self.stranger)
        self.assertEqual(self.client.post(self.path, data, format="json", **self.headers).status_code, 403)
        self.client.force_authenticate(self.tech)
        self.assertEqual(self.client.post(self.path, data, format="json", **self.headers).status_code, 403)
        self.assertEqual(self.client.get("/api/v1/business/tech-board/", **self.headers).status_code, 403)

    def test_tech_board_has_dispatcher_staff_and_unassigned_queue(self):
        result = self.client.post(
            self.path, {"customer_name": "Caller", "service_label": "Outlet repair"},
            format="json", **self.headers,
        )
        self.assertEqual(result.status_code, 201, result.data)
        board = self.client.get("/api/v1/business/tech-board/", **self.headers)
        self.assertEqual(board.status_code, 200)
        self.assertEqual(board.data["summary"]["unassigned"], 1)
        self.assertEqual(board.data["unassigned"][0]["ticket_id"], result.data["ticket_id"])
        self.assertTrue(any(x["user_id"] == self.tech.pk for x in board.data["staff"]))

    def test_founder_assist_creates_audited_ticket_without_impersonation(self):
        payload = {"customer_name": "Caller", "phone": "3345552121", "service_label": "Inspection"}
        path = f"/api/v1/platform/businesses/{self.business.pk}/assist/quick-intake/"
        self.client.force_authenticate(self.stranger)
        self.assertEqual(self.client.post(path, payload, format="json").status_code, 403)
        self.client.force_authenticate(self.founder)
        out = self.client.post(path, payload, format="json")
        self.assertEqual(out.status_code, 201, out.data)
        self.assertTrue(out.data["support_mode"])
        self.assertEqual(Ticket.objects.get(pk=out.data["ticket_id"]).customer_id, self.owner.id)
        audit = AuditLog.objects.get(action="business.phone_ticket_created")
        self.assertEqual(audit.actor_id, self.founder.pk)
        self.assertTrue(audit.metadata["founder_support"])
        c = self.client.get(f"/api/v1/platform/businesses/{self.business.pk}/assist/customers/")
        self.assertEqual(c.status_code, 200)
        self.assertEqual(len(c.data["customers"]), 1)
