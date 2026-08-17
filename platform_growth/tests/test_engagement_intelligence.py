from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from platform_growth.models import GrowthChannelConnection, GrowthContentDraft, GrowthContentQueueItem, GrowthOAuthToken
from platform_growth.services.engagement import growth_intelligence_for_user, refresh_posted_engagement


@pytest.mark.django_db
def test_refresh_posted_engagement_updates_metadata():
    user = get_user_model().objects.create_user(username="growth-engagement", email="growth-engagement@example.com", password="test-pass-123")
    connection = GrowthChannelConnection.objects.create(
        provider=GrowthChannelConnection.Provider.META,
        external_account_id="engagement-page-1",
        account_label="Test Page",
        status=GrowthChannelConnection.Status.CONNECTED,
        metadata={"account_kind": "facebook_page"},
        created_by=user,
    )
    GrowthOAuthToken.objects.create(connection=connection, provider="META", access_token="token", is_active=True, created_by=user)
    draft = GrowthContentDraft.objects.create(title="Local service tip", body="Tip", status=GrowthContentDraft.Status.APPROVED, created_by=user)
    item = GrowthContentQueueItem.objects.create(
        draft=draft,
        channel_connection=connection,
        status=GrowthContentQueueItem.Status.POSTED,
        posted_at=timezone.now() - timedelta(hours=2),
        metadata={"external_post_id": "engagement-page-1_123", "target_platform": "facebook"},
        created_by=user,
    )

    with patch(
        "platform_growth.services.engagement.fetch_post_engagement",
        return_value={"likes": 8, "comments": 3, "shares": 2, "total_engagement": 13, "permalink": "https://facebook.example/post"},
    ):
        counts = refresh_posted_engagement(user=user)

    item.refresh_from_db()
    assert counts["updated"] == 1
    assert item.metadata["engagement"]["total_engagement"] == 13
    assert item.metadata["engagement"]["shares"] == 2


@pytest.mark.django_db
def test_intelligence_ranks_top_content_and_recommends_winner_reuse():
    user = get_user_model().objects.create_user(username="growth-intel", email="growth-intel@example.com", password="test-pass-123")
    connection = GrowthChannelConnection.objects.create(
        provider=GrowthChannelConnection.Provider.META,
        external_account_id="engagement-page-2",
        account_label="Test Page",
        status=GrowthChannelConnection.Status.CONNECTED,
        metadata={"account_kind": "facebook_page"},
        created_by=user,
    )
    for idx, score in enumerate([2, 4, 20], start=1):
        draft = GrowthContentDraft.objects.create(title=f"Post {idx}", body="Body", status=GrowthContentDraft.Status.APPROVED, created_by=user)
        GrowthContentQueueItem.objects.create(
            draft=draft,
            channel_connection=connection,
            status=GrowthContentQueueItem.Status.POSTED,
            posted_at=timezone.now() - timedelta(hours=idx),
            metadata={"target_platform": "facebook", "engagement": {"likes": score, "comments": 0, "shares": 0, "total_engagement": score}},
            created_by=user,
        )

    data = growth_intelligence_for_user(user)
    assert data["posted_count"] == 3
    assert data["top_posts"][0]["title"] == "Post 3"
    assert data["top_posts"][0]["engagement"]["total"] == 20
    assert any(item["code"] == "REUSE_WINNER" for item in data["recommendations"])


@pytest.mark.django_db
def test_growth_intelligence_endpoint_is_user_scoped():
    User = get_user_model()
    user = User.objects.create_user(username="growth-api", email="growth-api@example.com", password="test-pass-123", role="SBO")
    other = User.objects.create_user(username="growth-other", email="growth-other@example.com", password="test-pass-123", role="SBO")

    for owner, external_id in [(user, "page-user"), (other, "page-other")]:
        connection = GrowthChannelConnection.objects.create(
            provider=GrowthChannelConnection.Provider.META,
            external_account_id=external_id,
            account_label=external_id,
            status=GrowthChannelConnection.Status.CONNECTED,
            created_by=owner,
        )
        draft = GrowthContentDraft.objects.create(title=external_id, body="Body", status=GrowthContentDraft.Status.APPROVED, created_by=owner)
        GrowthContentQueueItem.objects.create(
            draft=draft,
            channel_connection=connection,
            status=GrowthContentQueueItem.Status.POSTED,
            posted_at=timezone.now(),
            metadata={"engagement": {"likes": 4, "comments": 1, "shares": 0, "total_engagement": 5}},
            created_by=owner,
        )

    client = APIClient()
    client.force_authenticate(user=user)
    response = client.get("/api/v1/platform-growth/growth/intelligence/")
    assert response.status_code == 200
    assert response.data["posted_count"] == 1
    assert response.data["top_posts"][0]["title"] == "page-user"
