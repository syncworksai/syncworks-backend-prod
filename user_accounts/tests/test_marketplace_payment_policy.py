from decimal import Decimal
from django.test import SimpleTestCase
from user_accounts.services.marketplace_payment_policy import proposed_marketplace_quote


class FeePolicyQuoteTests(SimpleTestCase):
    def test_customer_pays_1_percent_in_addition_to_service(self):
        quote = proposed_marketplace_quote("100.00")
        self.assertEqual(quote.customer_platform_fee, Decimal("1.00"))
        self.assertEqual(quote.customer_total_before_tax, Decimal("101.00"))
        self.assertEqual(quote.connected_business_gross, Decimal("100.00"))
        self.assertEqual(quote.platform_gross_fee, Decimal("1.00"))

    def test_cent_rounding_and_disallowed_overrides(self):
        self.assertEqual(proposed_marketplace_quote("10.50").customer_platform_fee, Decimal("0.11"))
        for amount in ["-1.00", "1.001", "NaN", "Infinity"]:
            with self.assertRaises(ValueError):
                proposed_marketplace_quote(amount)
        with self.assertRaises(ValueError):
            proposed_marketplace_quote("100.00", platform_fee_bps=200)
