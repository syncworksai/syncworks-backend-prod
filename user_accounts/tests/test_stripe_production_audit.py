from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from user_accounts.models import Business, PlatformBillingProfile, User, UserBillingProfile


@override_settings(STRIPE_SECRET_KEY="sk_test_123", STRIPE_WEBHOOK_SECRET="whsec_test")
class TestStripeWebhookUserSubscriptions(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="stripe-user@test.com",
            email="stripe-user@test.com",
            password="Password123!",
            role="CUSTOMER",
        )

    @patch("user_accounts.viewsets.platform_billing.stripe.Subscription.retrieve")
    @patch("user_accounts.viewsets.platform_billing.stripe.Webhook.construct_event")
    def test_checkout_session_completed_subscription_updates_user_profile(self, mock_construct, mock_sub_retrieve):
        mock_construct.return_value = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "mode": "subscription",
                    "customer": "cus_user_123",
                    "subscription": "sub_user_123",
                    "metadata": {"user_id": str(self.user.id), "scope": "user"},
                }
            },
        }
        mock_sub_retrieve.return_value = {
            "id": "sub_user_123",
            "status": "active",
            "cancel_at_period_end": False,
            "current_period_end": int(timezone.now().timestamp()) + 3600,
        }

        response = self.client.post(
            "/api/v1/stripe/webhook/",
            data=b"{}",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="sig",
        )

        self.assertEqual(response.status_code, 200)
        prof = UserBillingProfile.objects.get(user=self.user)
        self.assertEqual(prof.stripe_customer_id, "cus_user_123")
        self.assertEqual(prof.stripe_subscription_id, "sub_user_123")
        self.assertEqual(prof.subscription_status, "active")

    @patch("user_accounts.viewsets.platform_billing.stripe.Webhook.construct_event")
    def test_customer_subscription_updated_updates_user_profile(self, mock_construct):
        prof = UserBillingProfile.objects.create(
            user=self.user,
            stripe_customer_id="cus_user_abc",
            stripe_subscription_id="sub_old",
            subscription_status="incomplete",
        )
        mock_construct.return_value = {
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_new",
                    "customer": "cus_user_abc",
                    "status": "trialing",
                    "cancel_at_period_end": False,
                    "current_period_end": int(timezone.now().timestamp()) + 7200,
                }
            },
        }

        response = self.client.post(
            "/api/v1/stripe/webhook/",
            data=b"{}",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="sig",
        )

        self.assertEqual(response.status_code, 200)
        prof.refresh_from_db()
        self.assertEqual(prof.stripe_subscription_id, "sub_new")
        self.assertEqual(prof.subscription_status, "trialing")


class TestSubscriptionCancelFlow(APITestCase):
    @override_settings(STRIPE_SECRET_KEY="sk_test_123")
    @patch("user_accounts.viewsets.subscriptions.stripe.Subscription.modify")
    def test_business_cancel_subscription_does_not_crash_on_period_end(self, mock_modify):
        owner = User.objects.create_user(
            username="owner@test.com",
            email="owner@test.com",
            password="Password123!",
            role="SBO",
        )
        token = Token.objects.create(user=owner)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        biz = Business.objects.create(name="Stripe Biz", owner=owner)
        prof, _ = PlatformBillingProfile.objects.get_or_create(business=biz)
        prof.stripe_subscription_id = "sub_biz_123"
        prof.subscription_status = "active"
        prof.save(update_fields=["stripe_subscription_id", "subscription_status"])

        mock_modify.return_value = {
            "cancel_at_period_end": True,
            "status": "active",
            "current_period_end": int(timezone.now().timestamp()) + 1800,
        }

        response = self.client.post(
            "/api/v1/billing/subscription/cancel/",
            {"business_id": biz.id},
            format="json",
            HTTP_X_BUSINESS_ID=str(biz.id),
        )

        self.assertEqual(response.status_code, 200)
