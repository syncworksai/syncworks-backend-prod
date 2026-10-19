from django.test import SimpleTestCase

from user_accounts.models.platform_billing import MonthlyPlatformBill, PlatformPricing


class AllSubscriptionsWaivedButPlatformFeeTests(SimpleTestCase):
    def test_swff26_style_waiver_never_waives_the_one_percent(self):
        class Profile:
            def extra_seats(self, pricing):
                return 3

        pricing=PlatformPricing()
        result=MonthlyPlatformBill.compute_amounts(
            profile=Profile(), pricing=pricing,
            gross_paid_invoices_cents=100000,
            waive_subscriptions=True,
        )
        self.assertEqual(result["platform_fee_cents"], 1000)
        self.assertEqual(result["sbo_subscription_cents"], 0)
        self.assertEqual(result["pm_subscription_cents"], 0)
        self.assertEqual(result["seats_cents"], 0)
        self.assertEqual(result["total_due_cents"], 1000)

    def test_regular_billing_keeps_seats_and_subscription(self):
        class Profile:
            def extra_seats(self, pricing):
                return 2

        result=MonthlyPlatformBill.compute_amounts(
            profile=Profile(), pricing=PlatformPricing(),
            gross_paid_invoices_cents=100000,
            waive_subscriptions=False,
        )
        self.assertEqual(result["platform_fee_cents"], 1000)
        self.assertEqual(result["seats_cents"], 3000)
        self.assertEqual(result["sbo_subscription_cents"], 1999)
