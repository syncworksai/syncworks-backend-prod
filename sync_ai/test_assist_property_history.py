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

    def test_rent_keyword_not_embedded_in_current(self):
        profile = {"terms": ["rent"], "contacts": []}
        self.assertEqual(matches(msg("Current withdrawal", "Your current balance"), profile), [])
        self.assertEqual(matches(msg("Rent ledger"), profile), ["rent"])

    def test_sender_lookalike_not_trusted(self):
        profile = {"terms": [], "contacts": ["housing@city.example"]}
        self.assertEqual(matches(msg("Status", sender="housing@city.example.evil"), profile), [])
        self.assertEqual(matches(msg("Inspection", sender="housing@city.example"), profile),
                         ["contact:housing@city.example"])

    def test_generic_finance_unrelated_to_property(self):
        profile = {"terms": ["housing assistance", "inspection"], "contacts": []}
        self.assertEqual(matches(msg("Robinhood instant deposit"), profile), [])

    def test_sender_display_name_matches_property_search_terms(self):
        profile = {"terms": ["marcus poole"], "contacts": []}
        message = msg("Re: MHA packet", "Packet attached", "mpoole@mhatoday.org")
        message["from"]["emailAddress"]["name"] = "Marcus Poole"
        self.assertEqual(matches(message, profile), ["marcus poole"])

    def test_sender_email_address_matches_custom_search_term(self):
        profile = {"terms": ["mpoole@mhatoday.org"], "contacts": []}
        self.assertEqual(matches(msg("Re: MHA packet", sender="mpoole@mhatoday.org"), profile),
                         ["mpoole@mhatoday.org"])

    def test_reply_recipient_name_can_match_correspondence(self):
        profile = {"terms": ["dakesha norman"], "contacts": []}
        message = msg("RE: MHA packet", "Thank you for the update",
                      sender="property.owner@example.com")
        message["toRecipients"] = [{"emailAddress": {
            "name": "Dakesha Norman", "address": "dakesha@example.com"
        }}]
        self.assertEqual(matches(message, profile), ["dakesha norman"])

    def test_unrelated_promotions_are_not_matched(self):
        profile = {"terms": ["marcus poole", "adair realty", "roxana"], "contacts": []}
        self.assertEqual(matches(msg("50 percent off appliances", "Holiday sale"), profile), [])
