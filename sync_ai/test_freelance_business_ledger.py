from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.core.cache import cache
from rest_framework.test import APIClient

ROOT="/api/v1/sync-ai/freelance/pilot/business-ledger/"

class BusinessLedgerTests(TestCase):
    def setUp(self):
        # Each test is isolated from the rate limiter's shared cache.
        cache.clear()
        User=get_user_model()
        self.owner=User.objects.create_user(username="ledger-owner",email="jacoblord7@outlook.com",password="x")
        self.owner.email_verified=True
        self.owner.save(update_fields=["email_verified"])
        self.other=User.objects.create_user(username="ledger-other",email="other@example.com",password="x")
        self.scope=override_settings(FREELANCE_PILOT_USER_ID=str(self.owner.pk))
        self.scope.enable()
        self.addCleanup(self.scope.disable)
        self.client=APIClient()

    def test_private_owner_only(self):
        self.assertEqual(self.client.get(ROOT).status_code,401)
        self.client.force_authenticate(user=self.other)
        self.assertEqual(self.client.get(ROOT).status_code,403)
        self.client.force_authenticate(user=self.owner)
        self.assertEqual(self.client.get(ROOT).status_code,200)

    def test_financial_stages_and_owner_scope(self):
        self.client.force_authenticate(user=self.owner)
        response=self.client.post(ROOT,{"title":"Sample data cleanup","expected_gross":"100.00","status":"SAVED"},format="json")
        self.assertEqual(response.status_code,201,response.data)
        rid=response.data["record_id"]
        result=self.client.patch(ROOT+rid+"/",{"status":"HIRED","contract_gross":"80.00","billed_gross":"0.00","paid_gross":"0.00"},format="json")
        self.assertEqual(result.status_code,200,result.data)
        data=self.client.get(ROOT).data
        self.assertEqual(data["summary"]["potential_gross"],"100.00")
        self.assertEqual(data["summary"]["contracted_gross"],"80.00")
        self.assertEqual(data["summary"]["received_gross"],"0")
        self.assertFalse(data["summary"]["verified_upwork_feed"])
        expense=self.client.post(ROOT,{"category":"EXPENSE","title":"Application supplies","cash_spent":"4.00","connects_used":10},format="json")
        self.assertEqual(expense.status_code,201,expense.data)
        totals=self.client.get(ROOT).data["summary"]
        self.assertEqual(totals["cash_expenses"],"4.00")
        self.assertEqual(totals["connects_used"],10)
        self.client.force_authenticate(user=self.other)
        self.assertEqual(self.client.patch(ROOT+rid+"/",{"status":"PAID"},format="json").status_code,403)

    def test_cannot_fake_upwork_confirmation_or_inject_bad_amounts(self):
        self.client.force_authenticate(user=self.owner)
        for amount in ["NaN","Infinity","-5","123.333"]:
            self.assertEqual(self.client.post(ROOT,{"title":"Bad","paid_gross":amount},format="json").status_code,400)
        for source in ["UPWORK_CONFIRMED","CHATGPT_VERIFIED"]:
            self.assertEqual(self.client.post(ROOT,{"title":"Bad","source":source},format="json").status_code,400)
        self.assertEqual(self.client.post(ROOT,{"title":"Bad","url":"http://phishing.example.com"},format="json").status_code,400)
