from uuid import uuid4
from django.test import override_settings
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from user_accounts.models import AuditLog, Business, Ticket

URL="/api/v1/sync-ai/assist/pilot/assignments/"

@override_settings(REST_FRAMEWORK={
    "DEFAULT_AUTHENTICATION_CLASSES":["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES":["rest_framework.permissions.IsAuthenticated"],
})
class AIAssignmentIntakeTests(APITestCase):
    def setUp(self):
        User=get_user_model()
        self.owner=User.objects.create_user(username="ai-assignment-owner",email="jacoblord7@outlook.com",password="test12345")
        self.other=User.objects.create_user(username="ai-assignment-other",email="other-ai@example.com",password="test12345")
        self.client.force_authenticate(self.owner)

    def test_create_and_retry_idempotently_without_external_side_effect(self):
        request_id=str(uuid4())
        payload={"request_id":request_id,"kind":"TASK","role":"CHIEF_OF_STAFF",
                 "description":"Review the new request backlog and identify what needs human approval."}
        first=self.client.post(URL,payload,format="json")
        self.assertEqual(first.status_code,201,first.data)
        self.assertTrue(first.data["created"])
        self.assertEqual(first.data["assignment"]["state"],"AWAITING_REVIEW")
        self.assertEqual(first.data["assignment"]["ticket_id"],None)
        second=self.client.post(URL,payload,format="json")
        self.assertEqual(second.status_code,200,second.data)
        self.assertFalse(second.data["created"])
        self.assertEqual(AuditLog.objects.filter(actor=self.owner,action="sync_assist.assignment.created").count(),1)

    def test_ticket_work_requires_existing_authorized_ticket(self):
        bad=self.client.post(URL,{"request_id":str(uuid4()),"kind":"TICKET","role":"CHIEF_OF_STAFF",
                        "description":"Review ticket.","ticket_id":99999999},format="json")
        self.assertEqual(bad.status_code,404,bad.data)
        missing=self.client.post(URL,{"request_id":str(uuid4()),"kind":"TICKET","role":"CHIEF_OF_STAFF",
                        "description":"Review ticket."},format="json")
        self.assertEqual(missing.status_code,400,missing.data)

    def test_reject_unknown_role_and_non_pilot(self):
        bad=self.client.post(URL,{"request_id":str(uuid4()),"kind":"TASK","role":"ROOT_ADMIN",
                         "description":"Manage everything"},format="json")
        self.assertEqual(bad.status_code,400,bad.data)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(URL).status_code,403)
        self.assertEqual(self.client.post(URL,{"request_id":str(uuid4()),"kind":"TASK","role":"CHIEF_OF_STAFF","description":"Test."},format="json").status_code,403)

    def test_review_is_not_execution(self):
        created=self.client.post(URL,{"request_id":str(uuid4()),"kind":"TASK","role":"CHIEF_OF_STAFF",
                        "description":"Review the queue."},format="json")
        self.assertEqual(created.status_code,201,created.data)
        ident=created.data["assignment"]["assignment_id"]
        response=self.client.post(f"{URL}{ident}/decision/",{"state":"ACKNOWLEDGED"},format="json")
        self.assertEqual(response.status_code,200,response.data)
        self.assertEqual(response.data["assignments"][0]["state"],"ACKNOWLEDGED")
        self.assertFalse(AuditLog.objects.filter(actor=self.owner,action="sync_assist.workday.worker_receipt").exists())

    def test_new_owner_business_ticket_auto_creates_one_victoria_review(self):
        business=Business.objects.create(name="Pilot Operations",owner=self.owner)
        with self.captureOnCommitCallbacks(execute=True):
            ticket=Ticket.objects.create(customer=self.other,assigned_business=business,
                status="NEW",work_title="Test plumbing repair")
        auto=AuditLog.objects.filter(actor=self.owner,action="sync_assist.assignment.created",
                                     metadata__automatic_ticket_id=ticket.pk)
        self.assertEqual(auto.count(),1)
        self.assertEqual(auto.first().metadata["role"],"CHIEF_OF_STAFF")
        self.assertEqual(auto.first().metadata["source"],"AUTO_TICKET_INTAKE")
        with self.captureOnCommitCallbacks(execute=True):
            ticket.status="ASSIGNED"
            ticket.save(update_fields=["status"])
        self.assertEqual(auto.count(),1)

    def test_unrelated_business_never_creates_founder_ai_task(self):
        business=Business.objects.create(name="Outside Operations",owner=self.other)
        with self.captureOnCommitCallbacks(execute=True):
            Ticket.objects.create(customer=self.owner,assigned_business=business,
                                  status="NEW",work_title="Other company job")
        self.assertEqual(AuditLog.objects.filter(actor=self.owner,
            action="sync_assist.assignment.created",metadata__source="AUTO_TICKET_INTAKE").count(),0)

    def test_employee_work_inbox_is_fixed_role_scoped_and_review_only(self):
        for role in ("CHIEF_OF_STAFF", "FINANCE_MANAGER"):
            created=self.client.post(URL,{"request_id":str(uuid4()),"kind":"TASK","role":role,
                "description":f"Review {role} priorities."},format="json")
            self.assertEqual(created.status_code,201,created.data)
        chief=self.client.get("/api/v1/sync-ai/assist/pilot/employees/CHIEF_OF_STAFF/work/")
        finance=self.client.get("/api/v1/sync-ai/assist/pilot/employees/FINANCE_MANAGER/work/")
        self.assertEqual(chief.status_code,200,chief.data)
        self.assertEqual(finance.status_code,200,finance.data)
        self.assertEqual(chief.data["pending_count"],1)
        self.assertEqual(finance.data["pending_count"],1)
        self.assertEqual(len(chief.data["assignments"]),1)
        self.assertEqual(len(finance.data["assignments"]),1)
        self.assertTrue(chief.data["internal_worker_available"])
        self.assertFalse(finance.data["internal_worker_available"])
        self.assertEqual(chief.data["execution_mode"],"REVIEW_ONLY")

    def test_employee_work_inbox_reflects_ticket_status_changes_without_mutation(self):
        business=Business.objects.create(name="Pilot Work Inbox",owner=self.owner)
        with self.captureOnCommitCallbacks(execute=True):
            ticket=Ticket.objects.create(customer=self.other,assigned_business=business,
                status="NEW",work_title="Plumbing job for review")
        first=self.client.get("/api/v1/sync-ai/assist/pilot/employees/CHIEF_OF_STAFF/work/")
        self.assertEqual(first.status_code,200,first.data)
        assigned=next(row for row in first.data["assignments"] if row["ticket_id"]==ticket.pk)
        self.assertEqual(assigned["ticket_status"],"NEW")
        self.assertFalse(assigned["status_changed_since_review"])
        self.assertTrue(assigned["recommendation_is_historical"])
        with self.captureOnCommitCallbacks(execute=True):
            ticket.status="IN_PROGRESS"
            ticket.save(update_fields=["status"])
        newer=self.client.get("/api/v1/sync-ai/assist/pilot/employees/CHIEF_OF_STAFF/work/")
        assigned=next(row for row in newer.data["assignments"] if row["ticket_id"]==ticket.pk)
        self.assertEqual(assigned["ticket_status"],"IN_PROGRESS")
        self.assertTrue(assigned["status_changed_since_review"])

    def test_non_pilot_cannot_read_any_employee_work_inbox(self):
        self.client.post(URL,{"request_id":str(uuid4()),"kind":"TASK","role":"FINANCE_MANAGER",
            "description":"Review invoice queue."},format="json")
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get("/api/v1/sync-ai/assist/pilot/employees/FINANCE_MANAGER/work/").status_code,403)
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.get("/api/v1/sync-ai/assist/pilot/employees/ROOT_ADMIN/work/").status_code,404)
