from datetime import datetime

from django.test import SimpleTestCase
from django.utils import timezone

from sync_ai.marketplace_views import _next_quarter_hour


class MarketplaceSlotBoundaryTests(SimpleTestCase):
    def test_exact_quarter_hour_with_elapsed_seconds_moves_forward(self):
        current = timezone.make_aware(
            datetime(2026, 8, 24, 14, 45, 3),
            timezone.get_current_timezone(),
        )
        candidate = _next_quarter_hour(current)
        self.assertGreater(candidate, current)
        self.assertEqual(candidate.minute, 0)
        self.assertEqual(candidate.hour, 15)
        self.assertEqual(candidate.second, 0)

    def test_non_boundary_rounds_up_to_next_quarter(self):
        current = timezone.make_aware(
            datetime(2026, 8, 24, 14, 37, 15),
            timezone.get_current_timezone(),
        )
        candidate = _next_quarter_hour(current)
        self.assertGreater(candidate, current)
        self.assertEqual(candidate.hour, 14)
        self.assertEqual(candidate.minute, 45)
