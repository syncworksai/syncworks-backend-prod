from unittest.mock import patch

from django.test import SimpleTestCase

from sync_ai.drive_state import build_drive_state


class DriveStateProjectionTests(SimpleTestCase):
    @patch("sync_ai.drive_state.enrich_daily_state_with_inbox")
    @patch("sync_ai.drive_state.build_daily_state")
    def test_drive_state_allow_lists_driver_safe_fields(self, build_daily, enrich):
        build_daily.return_value = {}
        enrich.return_value = {
            "local_date": "2026-10-02",
            "generated_at": "2026-10-02T17:00:00-05:00",
            "calendar": {
                "events": [{
                    "id": 1,
                    "title": "HVAC appointment",
                    "start_at": "2026-10-02T18:00:00-05:00",
                    "end_at": None,
                    "location": "Home",
                    "address": "123 Main St",
                    "departure": {"available": True, "leave_by": "2026-10-02T17:30:00-05:00"},
                    "travel": {"minutes": 20},
                    "url": "/customer/calendar",
                }],
                "next_event": {
                    "id": 1,
                    "title": "HVAC appointment",
                    "start_at": "2026-10-02T18:00:00-05:00",
                    "end_at": None,
                    "location": "Home",
                    "address": "123 Main St",
                    "departure": {},
                },
            },
            "inbox": {
                "total_unread": 99,
                "syncworks": {
                    "conversations": [{
                        "id": 9,
                        "title": "HVAC appointment",
                        "provider": "ABC HVAC",
                        "status": "Scheduled",
                        "latest_message": "On the way",
                        "latest_message_at": "2026-10-02T16:45:00-05:00",
                        "unread": True,
                        "needs_attention": False,
                        "url": "/customer/inbox?ticket=9",
                    }]
                },
                "external_email": {"messages": [{"subject": "private"}], "unread_count": 98},
            },
            "personal_requests": {
                "items": [{
                    "id": 9,
                    "code": "SW-9",
                    "title": "HVAC appointment",
                    "status": "SCHEDULED",
                    "status_label": "Scheduled",
                    "provider": "ABC HVAC",
                    "created_at": "2026-10-01T12:00:00Z",
                    "url": "/customer/requests/9",
                }]
            },
            "needs_attention": [
                {"category": "calendar", "priority": "high", "title": "Leave soon", "detail": "Leave by 5:30"},
                {"category": "money", "priority": "high", "title": "Card due", "detail": "$200"},
                {"category": "health", "priority": "normal", "title": "Workout", "detail": "Chest day"},
            ],
            "money": {"checking": [{"balance": 5000}]},
            "health": {"today": {"weight": 200}},
        }

        payload = build_drive_state(object())

        self.assertEqual(payload["unread_count"], 1)
        self.assertEqual(payload["events"][0]["address"], "123 Main St")
        self.assertEqual(payload["messages"][0]["latest_message"], "On the way")
        self.assertEqual([row["category"] for row in payload["attention"]], ["calendar"])
        self.assertNotIn("money", payload)
        self.assertNotIn("health", payload)
        self.assertNotIn("external_email", payload)
        self.assertNotIn("travel", payload["events"][0])
        self.assertNotIn("url", payload["messages"][0])
