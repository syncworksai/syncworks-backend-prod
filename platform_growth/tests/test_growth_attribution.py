from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from platform_growth.models import (
    GrowthChannelConnection,
    GrowthContentDraft,
    GrowthContentQueueItem,
    PlatformLead,
)


User = get_user_model()


@override_settings(GOD_MODE_EMAIL_ALLOWLIST=["god-growth@example.com"])
class GrowthAttributionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(
            username="growth-owner@example.com",
            email="growth-owner@example.com",
            password="Password123!",
            role="SBO",
        )
        self.other = User.objects.create_user(
            username="growth-other@example.com",
            email="growth-other@example.com",
            password="Password123!",
            role="SBO",
        )
        self.connection = GrowthChannelConnection.objects.create(
            provider=GrowthChannelConnection.Provider.META,
            account_label="Growth Test Page",
            external_account_id="page-growth-123",
            status=GrowthChannelConnection.Status.CONNECTED,
            created_by=self.owner,
        )

    def test_meta_webhook_assigns_lead_to_connected_business_and_keeps_referral_post(self):
        payload = {
            "object": "page",
            "entry": [
                {
                    "id": "page-growth-123",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messages": [
                                    {
                                        "from": "social-person-1",
                                        "id": "social-message-1",
                                        "text": {"body": "Can I get a quote?"},
                                        "referral": {"source": "POST", "post_id": "page-growth-123_post-9"},
                                    }
                                ]
                            },
                        }
                    ],
                }
            ],
        }

        response = self.client.post("/api/v1/platform-growth/meta/webhook/", payload, format="json")
        self.assertEqual(response.status_code, 202)

        lead = PlatformLead.objects.get(external_id="social-person-1")
        self.assertEqual(lead.assigned_to, self.owner)
        self.assertEqual(lead.metadata["social_connection_id"], self.connection.id)
        self.assertEqual(lead.metadata["source_post_id"], "page-growth-123_post-9")

        self.client.force_authenticate(user=self.owner)
        owner_leads = self.client.get("/api/v1/platform-growth/leads/")
        self.assertEqual(owner_leads.status_code, 200)
        owner_rows = owner_leads.data.get("results", owner_leads.data)
        self.assertEqual(len(owner_rows), 1)

        self.client.force_authenticate(user=self.other)
        other_leads = self.client.get("/api/v1/platform-growth/leads/")
        other_rows = other_leads.data.get("results", other_leads.data)
        self.assertEqual(len(other_rows), 0)

    def test_growth_intelligence_ranks_social_business_impact(self):
        draft = GrowthContentDraft.objects.create(
            title="Emergency repair tip",
            body="Helpful post",
            status=GrowthContentDraft.Status.APPROVED,
            created_by=self.owner,
        )
        GrowthContentQueueItem.objects.create(
            draft=draft,
            channel_connection=self.connection,
            status=GrowthContentQueueItem.Status.POSTED,
            posted_at=timezone.now(),
            metadata={
                "external_post_id": "page-growth-123_post-10",
                "target_platform": "facebook",
                "engagement": {"likes": 8, "comments": 2, "shares": 1, "total_engagement": 11},
            },
            created_by=self.owner,
        )
        PlatformLead.objects.create(
            source="META",
            external_id="lead-from-post",
            full_name="Lead From Post",
            assigned_to=self.owner,
            status=PlatformLead.Status.WON,
            metadata={"source_post_id": "page-growth-123_post-10"},
        )
        PlatformLead.objects.create(
            source="META",
            external_id="unattributed-lead",
            full_name="Other Social Lead",
            assigned_to=self.owner,
            status=PlatformLead.Status.NEW,
        )

        self.client.force_authenticate(user=self.owner)
        response = self.client.get("/api/v1/platform-growth/growth/intelligence/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["attributed_leads"], 1)
        self.assertEqual(response.data["won_leads"], 1)
        self.assertEqual(response.data["social_leads_total"], 2)
        self.assertEqual(response.data["unattributed_social_leads"], 1)
        self.assertEqual(response.data["top_posts"][0]["attribution"]["leads"], 1)
        self.assertEqual(response.data["top_posts"][0]["attribution"]["wins"], 1)
        self.assertEqual(response.data["top_posts"][0]["impact_score"], 36)
        self.assertEqual(response.data["recommendations"][0]["code"], "REUSE_CONVERTER")
