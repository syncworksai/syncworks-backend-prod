from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from user_accounts.models import Business
from .models import BusinessFeatureEntitlement
from .services import has_feature, estimate_cost_cents

class FeatureEntitlementTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="ent-owner", email="owner-ent@example.test", password="testpass12345")
        self.stranger = User.objects.create_user(username="ent-stranger", email="stranger-ent@example.test", password="testpass12345")
        self.founder = User.objects.create_user(username="ent-founder", email="founder-ent@example.test", password="testpass12345", is_superuser=True)
        self.business = Business.objects.create(owner=self.owner, name="Entitlement Test Shop")
        self.client = APIClient()

    def test_trial_starts_once_and_expires(self):
        self.client.force_authenticate(self.owner)
        endpoint = f"/api/v1/feature-entitlements/businesses/{self.business.pk}/trial/"
        res = self.client.post(endpoint, {"feature":"business_jarvis"},format="json")
        self.assertEqual(res.status_code,200,res.data)
        self.assertTrue(has_feature(self.business, "business_jarvis"))
        self.assertEqual(self.client.post(endpoint, {"feature":"business_jarvis"},format="json").status_code,400)
        row = BusinessFeatureEntitlement.objects.get(business=self.business,feature="business_jarvis")
        row.trial_expires_at = timezone.now() - timedelta(minutes=1)
        row.save()
        self.assertFalse(has_feature(self.business, "business_jarvis"))

    def test_stranger_cannot_see_or_start_business_trial(self):
        self.client.force_authenticate(self.stranger)
        self.assertEqual(self.client.get(f"/api/v1/feature-entitlements/businesses/{self.business.pk}/").status_code,403)
        self.assertEqual(self.client.post(f"/api/v1/feature-entitlements/businesses/{self.business.pk}/trial/",{"feature":"ai_weather"},format="json").status_code,403)

    def test_founder_override_requires_reason_and_expires(self):
        endpoint = f"/api/v1/feature-entitlements/god/businesses/{self.business.pk}/override/"
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.post(endpoint,{"feature":"ai_weather","state":"OVERRIDE","reason":"pilot"},format="json").status_code,403)
        self.client.force_authenticate(self.founder)
        self.assertEqual(self.client.post(endpoint,{"feature":"ai_weather","state":"OVERRIDE"},format="json").status_code,400)
        self.assertEqual(self.client.post(endpoint,{"feature":"ai_weather","state":"OVERRIDE","reason":"pilot","days":7},format="json").status_code,200)
        self.assertTrue(has_feature(self.business,"ai_weather"))

    def test_cost_meter_fails_closed_without_config(self):
        with patch.dict("os.environ",{},clear=True):
            with self.assertRaises(Exception):
                estimate_cost_cents(100,100)
        with patch.dict("os.environ",{"SYNC_AI_INPUT_USD_PER_MILLION":"1","SYNC_AI_OUTPUT_USD_PER_MILLION":"4"}):
            self.assertEqual(estimate_cost_cents(100000,50000),30)
