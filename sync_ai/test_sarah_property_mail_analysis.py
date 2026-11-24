"""Bounded Sarah classifier regression tests. No Microsoft requests are sent."""
from django.test import SimpleTestCase
from .assist_property_mail_analysis import classify


def message(subject, preview="", sender="housing@example.org"):
    return {"id":"message-123", "subject":subject,
            "bodyPreview":preview, "receivedDateTime":"2026-11-24T12:00:00Z",
            "from":{"emailAddress":{"address":sender}}}


class SarahClassifierTests(SimpleTestCase):
    def test_inspection_with_source(self):
        row=classify(message("Reinspection requested", "Please confirm the proposed time."))
        self.assertEqual(row["category"], "INSPECTION")
        self.assertEqual(row["message_id"], "message-123")
        self.assertEqual(row["fact_status"], "NEEDS_SOURCE_VERIFICATION")
        self.assertFalse(row["proposed_reply"]["send_enabled"])

    def test_abatement_is_payment_review_not_confirmed_balance(self):
        row=classify(message("Housing assistance abatement notice"))
        self.assertEqual(row["category"], "PAYMENT")
        self.assertEqual(row["priority"], "HIGH")
        self.assertIn("Compare", row["proposed_action"])

    def test_promotional_mail_not_a_property_finding(self):
        self.assertIsNone(classify(message("Black Friday deals are here",
                  "Book your appointment now", "promos@retailer.example")))

    def test_mha_word_boundary(self):
        self.assertIsNone(classify(message("Happy birthday", "",
                                   "friend@personal.example")))
        row=classify(message("HAP payment", "", "sender@example.org"))
        self.assertEqual(row["category"], "PAYMENT")

    def test_unrelated_personal_mail_does_not_trigger(self):
        self.assertIsNone(classify(message("Dinner tonight?", "See you at seven",
                                   "friend@example.org")))
