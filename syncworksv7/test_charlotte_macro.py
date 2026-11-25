from datetime import date
from unittest.mock import patch
from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory, force_authenticate
from types import SimpleNamespace
from .charlotte_macro import observations, macro

class CharlotteMacroTests(SimpleTestCase):
    def test_missing_and_nonfinite_values_are_not_zero(self):
        rows = [{"date":"2020-01-01","value":"."},{"date":"2020-01-02","value":"NaN"},{"date":"2020-01-03","value":"0"},{"date":"2020-01-04","value":"2.5"}]
        self.assertEqual(observations(rows), [{"date":"2020-01-03","value":0.0},{"date":"2020-01-04","value":2.5}])
    def test_sorted_and_future_excluded(self):
        self.assertEqual(observations([{"date":"2020-02-01","value":"2"},{"date":"2020-01-01","value":"1"},{"date":"9999-01-01","value":"3"}]), [{"date":"2020-01-01","value":1.0},{"date":"2020-02-01","value":2.0}])
    @patch.dict("os.environ", {"CHARLOTTE_PILOT_EMAIL":"pilot@example.invalid"})
    def test_other_user_denied(self):
        request = APIRequestFactory().get("/")
        force_authenticate(request, user=SimpleNamespace(is_authenticated=True,email="other@example.invalid"))
        self.assertEqual(macro(request).status_code,403)
    @patch.dict("os.environ", {"CHARLOTTE_PILOT_EMAIL":"pilot@example.invalid","CHARLOTTE_FRED_KEY":""})
    def test_unconfigured_provider_fails_closed(self):
        request = APIRequestFactory().get("/")
        force_authenticate(request, user=SimpleNamespace(is_authenticated=True,email="pilot@example.invalid"))
        self.assertEqual(macro(request).status_code,503)
