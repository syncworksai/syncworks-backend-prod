"""Tests to prevent specialist routing and inadvertent filing regressions."""
from django.test import SimpleTestCase
from .assist_mail_router import route


def msg(subject, sender="user@example.org", preview=""):
    return {"id": "m1", "subject": subject, "bodyPreview": preview,
            "from": {"emailAddress": {"address": sender}},
            "receivedDateTime": "2026-11-24T14:00:00Z"}


class RoutingTests(SimpleTestCase):
    def test_property_inspection_to_sarah(self):
        result = route(msg("MHA reinspection date", "housingauthority@example.org"))
        self.assertEqual(result["category"], "PROPERTY")
        self.assertEqual(result["assistant"], "Sarah · Property Manager")
        self.assertFalse(result["outlook_modified"])

    def test_robinhood_goes_to_markets_not_property(self):
        result = route(msg("Funds available for investing",
                           "noreply@robinhood.com",
                           "Instant deposit from your bank transfer"))
        self.assertEqual(result["category"], "MARKETS")

    def test_student_loan_goes_to_finance_not_sarah(self):
        result = route(msg("Avoid default on your account",
                           "noreply@nelnet.studentaid.gov",
                           "Your account is six months past due"))
        self.assertEqual(result["category"], "FINANCE")

    def test_sales_promotion_is_personal_review(self):
        result = route(msg("Black Friday 50% off",
                           "marketing@retail.example", "Shop now! Unsubscribe"))
        self.assertEqual(result["category"], "PERSONAL")
        self.assertEqual(result["filing_action"], "SUGGEST_FOLDER")

    def test_unclassified_kept_for_victoria(self):
        result = route(msg("Hello", "friend@example.org"))
        self.assertEqual(result["category"], "REVIEW")
        self.assertEqual(result["filing_action"], "KEEP_IN_INBOX")

    def test_debt_relief_email_goes_to_finance(self):
        result = route(msg("Re: Emily from Pacific Debt",
            "emily@engage.pacificdebt.com",
            "The bigger concern right now is monthly payments or balances"))
        self.assertEqual(result["category"], "FINANCE")
        self.assertEqual(result["priority"], "HIGH")
        self.assertEqual(result["filing_action"], "KEEP_IN_INBOX")

    def test_personalized_offer_goes_to_personal(self):
        result = route(msg("jacob, this offer is just for you",
            "noreply@email.sionicdriven.com",
            "Redeem your offer while it's here"))
        self.assertEqual(result["category"], "PERSONAL")

    def test_security_alert_protected(self):
        result = route(msg("Security alert: unusual sign-in",
                           "security@example.org"))
        self.assertEqual(result["category"], "REVIEW")
        self.assertEqual(result["priority"], "HIGH")
        self.assertEqual(result["filing_action"], "KEEP_IN_INBOX")

    def test_conflicting_categories_require_review(self):
        result = route(msg("Mortgage invoice for SyncWorks",
                           "bank@example.org"))
        self.assertEqual(result["category"], "REVIEW")
        self.assertEqual(result["confidence"], "LOW")
