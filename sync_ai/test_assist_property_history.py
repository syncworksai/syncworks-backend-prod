"""Historical search must respect configured property rather than hardcoded providers."""
from django.test import SimpleTestCase
from .assist_property_history import matches


def msg(subject="", preview="", sender="other@example.com"):
    return {"subject": subject, "bodyPreview": preview,
            "from": {"emailAddress": {"address": sender}}}


class PropertyHistoryMatchingTests(SimpleTestCase):
    def test_matches_configured_keyword(self):
        profile = {"terms": ["inspection"], "contacts": []}
        self.assertEqual(matches(msg("Reinspection scheduled"), profile), [])
        self.assertEqual(matches(msg("Inspection notice"), profile), ["inspection"])

    def test_matches_exact_contact_address(self):
        profile = {"terms": ["rent ledger"], "contacts": ["office@agency.example"]}
        self.assertEqual(matches(msg("Status update", sender="office@agency.example"), profile),
                         ["contact:office@agency.example"])
        self.assertEqual(matches(msg("Status update", sender="office@agency.example.attacker"), profile), [])

    def test_no_false_lease_match_inside_please(self):
        profile = {"terms": ["lease"], "contacts": []}
        self.assertEqual(matches(msg("Please respond"), profile), [])
        self.assertEqual(matches(msg("Lease agreement"), profile), ["lease"])

    def test_generic_finance_unrelated_to_property(self):
        profile = {"terms": ["housing assistance", "inspection"], "contacts": []}
        self.assertEqual(matches(msg("Robinhood instant deposit"), profile), [])
