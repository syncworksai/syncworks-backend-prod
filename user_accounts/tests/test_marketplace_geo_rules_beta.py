from types import SimpleNamespace

from django.test import SimpleTestCase

from user_accounts.services.tickets import _service_area_rule_matches


class MarketplaceGeographicRuleTests(SimpleTestCase):
    def setUp(self):
        self.ticket = SimpleNamespace()
        self.alabama = {"zip": "36117", "city": "MONTGOMERY", "state": "AL", "county": "MONTGOMERY"}
        self.florida = {"zip": "33101", "city": "MIAMI", "state": "FL", "county": "MIAMI-DADE"}

    def rule(self, kind, values):
        return {"area_type": kind, "values": values, "active": True, "project_scope": "BOTH"}

    def test_state_must_match_actual_state(self):
        rule = self.rule("STATE", ["AL"])
        self.assertTrue(_service_area_rule_matches(self.ticket, rule, self.alabama))
        self.assertFalse(_service_area_rule_matches(self.ticket, rule, self.florida))

    def test_city_and_state_qualified_name(self):
        rule = self.rule("CITY", ["Montgomery, AL"])
        self.assertTrue(_service_area_rule_matches(self.ticket, rule, self.alabama))
        self.assertFalse(_service_area_rule_matches(self.ticket, rule, self.florida))

    def test_multi_state_region_only_checks_states(self):
        rule = self.rule("REGION", ["AL", "GA"])
        self.assertTrue(_service_area_rule_matches(self.ticket, rule, self.alabama))
        self.assertFalse(_service_area_rule_matches(self.ticket, rule, self.florida))

    def test_inactive_state_coverage_never_matches(self):
        rule = self.rule("STATE", ["AL"])
        rule["active"] = False
        self.assertFalse(_service_area_rule_matches(self.ticket, rule, self.alabama))

    def test_missing_location_never_matches_state(self):
        self.assertFalse(_service_area_rule_matches(self.ticket, self.rule("STATE", ["AL"]), {}))
