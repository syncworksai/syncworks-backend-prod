"""Contract tests for safe property linking and name matching."""
from types import SimpleNamespace
from django.test import SimpleTestCase
from .assist_property_portfolio import property_terms
from .assist_property_history import matches


class PropertyPortfolioContractTests(SimpleTestCase):
    def test_exact_property_identifiers_only(self):
        prop = SimpleNamespace(name="Roxana Rd", address="123 Roxana Road")
        self.assertEqual(property_terms(prop), ["123 roxana road", "roxana rd"])

    def test_generic_keywords_not_auto_added_to_portfolio_profiles(self):
        prop = SimpleNamespace(name="Rental A", address="42 Main Street")
        terms = property_terms(prop)
        self.assertNotIn("rent", terms)
        self.assertNotIn("payment", terms)

    def test_named_sender_works_for_user_defined_terms(self):
        message = {
            "subject": "Update", "bodyPreview": "Following up",
            "from": {"emailAddress": {
                "name": "Marcus Poole",
                "address": "agent@example.com",
            }},
        }
        profile = {"terms": ["marcus poole"], "contacts": []}
        self.assertEqual(matches(message, profile), ["marcus poole"])

    def test_unrelated_payment_not_property_match(self):
        message = {"subject": "Your current withdrawal",
                   "bodyPreview": "We received your withdrawal request",
                   "from": {"emailAddress": {"name": "Support", "address": "notify@broker.com"}}}
        profile = {"terms": ["roxana rd", "123 roxana road"], "contacts": []}
        self.assertEqual(matches(message, profile), [])
