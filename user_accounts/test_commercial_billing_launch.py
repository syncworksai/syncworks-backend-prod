from django.test import SimpleTestCase
from unittest.mock import patch
from user_accounts.viewsets.subscriptions import _checkout_tax_options, _price_matches

class CommercialBillingLaunchTests(SimpleTestCase):
    def test_pending_blocks_live(self):
        with patch.dict("os.environ", {"SYNCWORKS_SUBSCRIPTION_TAX_MODE": "pending"}):
            with self.assertRaises(ValueError):
                _checkout_tax_options("sk_live_example")
            self.assertEqual(_checkout_tax_options("sk_test_example"), {"automatic_tax": {"enabled": False}})

    def test_explicit_tax_decisions(self):
        for mode, enabled in (("collect", True), ("do_not_collect", False)):
            with patch.dict("os.environ", {"SYNCWORKS_SUBSCRIPTION_TAX_MODE": mode}):
                self.assertEqual(_checkout_tax_options("sk_live_example")["automatic_tax"]["enabled"], enabled)

    def test_invalid_configuration_blocks(self):
        with patch.dict("os.environ", {"SYNCWORKS_SUBSCRIPTION_TAX_MODE": "invalid"}):
            with self.assertRaises(ValueError):
                _checkout_tax_options("sk_test_example")

    def test_price_validation(self):
        price = {"active": True, "currency": "usd", "unit_amount": 999, "recurring": {"interval": "month", "interval_count": 1, "usage_type": "licensed"}}
        self.assertTrue(_price_matches(price, "FINANCE"))
        self.assertTrue(_price_matches(price, "FITNESS"))
        for changes in ({"unit_amount": 99}, {"currency": "eur"}, {"active": False}, {"recurring": {"interval": "year"}}, {"recurring": {"interval": "month", "interval_count": 1, "usage_type": "metered"}}):
            self.assertFalse(_price_matches(dict(price, **changes), "FINANCE"))
