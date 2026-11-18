"""Coverage for quick slot suggestions and secure customer self-service invitations."""
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from personal_calendar.models import PersonalCalendarEvent
from user_accounts.models import Business, BusinessMember, Ticket, User, WorkforceProfile
from user_accounts.viewsets.customer_connection import send_customer_invitation


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",FRONTEND_URL="https://syncworksapp.com")
class ConnectedBusinessRequestTests(TestCase):
    def setUp(self):
        self.owner=User.objects.create_user(username="new-req-owner",email="owner-request@example.com",password="test")
        self.tech=User.objects.create_user(username="new-req-tech",email="tech-request@example.com",password="test")
        self.customer=User.objects.create_user(username="new-req-customer",email="customer-request@example.com",password="test",email_verified=True)
        self.business=Business.objects.create(name="Connection Test Company",owner=self.owner)
        self.member=BusinessMember.objects.create(user=self.tech,business=self.business,role="TECHNICIAN")
        self.profile=WorkforceProfile.objects.create(member=self.member,is_schedulable=True,weekly_availability={
            day:{"open":day not in ("saturday","sunday"),"start":"08:00","end":"17:00"}
            for day in ("monday","tuesday","wednesday","thursday","friday","saturday","sunday")
        })
        self.client=APIClient()
        self.headers={"HTTP_X_BUSINESS_ID":str(self.business.id)}

    def create_request(self):
        self.client.force_authenticate(self.owner)
        start=timezone.now()+timedelta(days=2)
        return self.client.post("/api/v1/business/quick-intake/",{
            "customer_name":"Customer","email":self.customer.email,
            "service_label":"Fixture repair","service_address":"123 Main St, Montgomery, AL 36104",
            "assigned_member_id":self.tech.id,"scheduled_start":start.isoformat(),
            "estimated_duration_minutes":60
        },format="json",**self.headers)

    def test_customer_claim_requires_verified_matching_account_and_adds_calendar(self):
        with self.captureOnCommitCallbacks(execute=True):
            created=self.create_request()
        self.assertEqual(created.status_code,201,created.data)
        ticket=Ticket.objects.get(pk=created.data["ticket_id"])
        self.assertFalse(ticket.customer_visible)
        self.assertEqual(len(mail.outbox),1)
        connection_url=mail.outbox[0].body.split("Connect your service request: ")[1].splitlines()[0]
        token=parse_qs(urlsplit(connection_url).query)["token"][0]
        self.client.force_authenticate(self.owner)
        denied=self.client.post("/api/v1/customer/connection/claim/",{"token":token},format="json")
        self.assertEqual(denied.status_code,403)
        self.client.force_authenticate(self.customer)
        accepted=self.client.post("/api/v1/customer/connection/claim/",{"token":token},format="json")
        self.assertEqual(accepted.status_code,200,accepted.data)
        ticket.refresh_from_db()
        self.assertTrue(ticket.customer_visible)
        self.assertEqual(ticket.customer_id,self.customer.id)
        self.assertTrue(PersonalCalendarEvent.objects.filter(
            owner=self.customer,source="TICKET",metadata__ticket_id=ticket.id,status="ACTIVE"
        ).exists())

    def test_business_and_technician_calendars_receive_scheduled_request(self):
        with self.captureOnCommitCallbacks(execute=True):
            result=self.create_request()
        self.assertEqual(result.status_code,201,result.data)
        ticket_id=result.data["ticket_id"]
        self.assertTrue(PersonalCalendarEvent.objects.filter(
            owner=self.owner,source="SYSTEM",metadata__ticket_id=ticket_id,status="ACTIVE"
        ).exists())
        self.assertTrue(PersonalCalendarEvent.objects.filter(
            owner=self.tech,source="TICKET",metadata__ticket_id=ticket_id,status="ACTIVE"
        ).exists())

    def test_suggestions_respect_closed_work_days(self):
        self.client.force_authenticate(self.owner)
        response=self.client.get("/api/v1/business/quick-intake/slots/",{
            "priority":"STANDARD","duration":60,"technician_id":self.tech.id,
            "timezone":"America/Chicago",
        },**self.headers)
        self.assertEqual(response.status_code,200,response.data)
        for slot in response.data["suggestions"]:
            self.assertLess(timezone.datetime.fromisoformat(slot["start"]).weekday(),5)
        self.assertFalse(response.data["verified_route"])
