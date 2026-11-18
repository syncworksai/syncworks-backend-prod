"""Regression tests for technician status, reassignment and customer/calendar sync."""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from personal_calendar.models import PersonalCalendarEvent
from user_accounts.models import Business, BusinessMember, Notification, Ticket, User, WorkforceProfile


class TechnicianHandoffTests(TestCase):
    def setUp(self):
        self.owner=User.objects.create_user(username="ops-owner",email="ops-owner@example.com",password="x")
        self.dispatch=User.objects.create_user(username="ops-dispatch",email="ops-dispatch@example.com",password="x")
        self.tech=User.objects.create_user(username="ops-tech",email="ops-tech@example.com",password="x")
        self.other=User.objects.create_user(username="ops-tech-2",email="ops-tech-2@example.com",password="x")
        self.stranger=User.objects.create_user(username="ops-outsider",email="ops-outsider@example.com",password="x")
        self.customer=User.objects.create_user(username="ops-customer",email="ops-customer@example.com",password="x",email_verified=True)
        self.biz=Business.objects.create(name="Dispatch QA",owner=self.owner)
        self.dm=BusinessMember.objects.create(business=self.biz,user=self.dispatch,role="DISPATCH",can_assign_tickets=True,can_manage_schedule=True)
        self.tm=BusinessMember.objects.create(business=self.biz,user=self.tech,role="TECHNICIAN")
        self.om=BusinessMember.objects.create(business=self.biz,user=self.other,role="TECHNICIAN")
        WorkforceProfile.objects.create(member=self.tm,skills=["plumbing"],is_schedulable=True,route_start_address="100 Start Street, Montgomery, AL")
        WorkforceProfile.objects.create(member=self.om,skills=["plumbing"],is_schedulable=True)
        self.client=APIClient()
        self.headers={"HTTP_X_BUSINESS_ID":str(self.biz.id)}
        self.client.force_authenticate(self.dispatch)
        start=timezone.now()+timedelta(hours=3)
        res=self.client.post("/api/v1/business/quick-intake/",{
            "customer_name":"Customer","email":"ops-customer@example.com",
            "service_address":"200 Destination Avenue, Montgomery, AL",
            "service_label":"Leak inspection","required_skills":["plumbing"],
            "assigned_member_id":self.tech.id,
            "scheduled_start":start.isoformat(),"estimated_duration_minutes":60,
        },format="json",**self.headers)
        self.assertEqual(res.status_code,201,res.data)
        self.ticket=Ticket.objects.get(pk=res.data["ticket_id"])

    def action(self,user,action,note=""):
        self.client.force_authenticate(user)
        return self.client.post(
            f"/api/v1/business/technician/jobs/{self.ticket.id}/action/",
            {"action":action,"note":note},format="json",**self.headers
        )

    def test_assigned_tech_can_start_and_customer_and_dispatch_are_notified(self):
        result=self.action(self.tech,"IN_PROGRESS")
        self.assertEqual(result.status_code,200,result.data)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status,"IN_PROGRESS")
        self.assertTrue(Notification.objects.filter(recipient=self.owner,data__source="BUSINESS_DISPATCH").exists())
        self.assertTrue(Notification.objects.filter(recipient=self.customer,type="TICKET").exists())
        self.assertTrue(PersonalCalendarEvent.objects.filter(owner=self.tech,source="TICKET",metadata__ticket_id=self.ticket.id).exists())

    def test_tech_release_returns_to_queue_and_ends_personal_calendar(self):
        res=self.action(self.tech,"RELEASE","Cannot attend today")
        self.assertEqual(res.status_code,200,res.data)
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.assigned_member_id)
        self.assertEqual(self.ticket.status,"NEW")
        self.assertEqual(PersonalCalendarEvent.objects.get(owner=self.tech,source="TICKET",metadata__ticket_id=self.ticket.id).status,"CANCELLED")
        self.assertTrue(Notification.objects.filter(recipient=self.owner,body__icontains="Cannot attend").exists())

    def test_other_tech_pickup_requires_dispatch_approval(self):
        self.client.force_authenticate(self.other)
        res=self.client.post(f"/api/v1/business/technician/jobs/{self.ticket.id}/pickup/",{},format="json",**self.headers)
        self.assertEqual(res.status_code,201,res.data)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.assigned_member_id,self.tech.id)
        self.client.force_authenticate(self.dispatch)
        approved=self.client.post(f"/api/v1/business/technician/pickups/{res.data['request_id']}/respond/",
            {"decision":"APPROVE"},format="json",**self.headers)
        self.assertEqual(approved.status_code,200,approved.data)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.assigned_member_id,self.other.id)

    def test_outsider_cannot_read_or_change_jobs(self):
        self.client.force_authenticate(self.stranger)
        board=self.client.get("/api/v1/business/technician/team-board/",**self.headers)
        update=self.client.post(f"/api/v1/business/technician/jobs/{self.ticket.id}/action/",
            {"action":"COMPLETED","note":"not mine"},format="json",**self.headers)
        self.assertEqual(board.status_code,403)
        self.assertEqual(update.status_code,403)

    def test_unassigned_tech_cannot_cancel_coworker_job(self):
        result=self.action(self.other,"CANCELLED","trying to cancel colleague")
        self.assertEqual(result.status_code,403)

    def test_en_route_uses_rounded_eta_not_false_live_gps(self):
        with patch("sync_ai.live_operations_views.live_travel",return_value={
            "minutes":23,"basis":"google_live_traffic"
        }):
            response=self.action(self.tech,"EN_ROUTE")
        self.assertEqual(response.status_code,200,response.data)
        self.assertIn("30 minutes",response.data.get("arrival_estimate") or "")
        self.assertIn("not a live GPS location",response.data.get("arrival_estimate") or "")
