from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from platform_growth.models import (
    GrowthAutomationRecipe,
    GrowthChannelConnection,
    GrowthContentDraft,
    GrowthContentQueueItem,
    GrowthOAuthToken,
    GrowthScheduledPostJob,
)
from platform_growth.services.posting import PublishResult, SocialPublishError
from platform_growth.services.runtime import (
    prepare_due_scheduled_posts,
    publish_ready_scheduled_posts,
    run_recipe,
)


@pytest.mark.django_db
def test_content_calendar_bot_creates_draft_without_sending():
    recipe = GrowthAutomationRecipe.objects.create(
        name="Content Calendar Bot",
        trigger_type="SCHEDULED",
        recipe={
            "bot_key": "content_calendar",
            "schedule": {"interval_minutes": 60},
            "template": {"title": "Tip", "body": "Helpful business tip."},
        },
    )

    result = run_recipe(recipe, force=True)

    assert result.status == "COMPLETED"
    assert result.data["outbound_sent"] is False
    draft = GrowthContentDraft.objects.get(id=result.data["draft_id"])
    assert draft.status == GrowthContentDraft.Status.DRAFT
    assert draft.metadata["requires_approval"] is True


@pytest.mark.django_db
def test_scheduled_post_does_not_become_ready_without_approval():
    connection = GrowthChannelConnection.objects.create(
        provider=GrowthChannelConnection.Provider.META,
        external_account_id="acct-1",
        status=GrowthChannelConnection.Status.CONNECTED,
    )
    draft = GrowthContentDraft.objects.create(
        title="Pending approval",
        body="Do not send yet",
        status=GrowthContentDraft.Status.DRAFT,
    )
    item = GrowthContentQueueItem.objects.create(
        draft=draft,
        channel_connection=connection,
        status=GrowthContentQueueItem.Status.SCHEDULED,
        scheduled_for=timezone.now() - timedelta(minutes=1),
    )
    job = GrowthScheduledPostJob.objects.create(
        queue_item=item,
        run_at=timezone.now() - timedelta(minutes=1),
    )

    counts = prepare_due_scheduled_posts()

    job.refresh_from_db()
    assert counts["ready"] == 0
    assert job.status == GrowthScheduledPostJob.Status.PENDING
    assert "not approved" in job.last_error


@pytest.mark.django_db
def test_approved_post_with_connected_channel_becomes_ready_not_published():
    connection = GrowthChannelConnection.objects.create(
        provider=GrowthChannelConnection.Provider.META,
        external_account_id="acct-2",
        status=GrowthChannelConnection.Status.CONNECTED,
    )
    draft = GrowthContentDraft.objects.create(
        title="Approved",
        body="Approved content",
        status=GrowthContentDraft.Status.APPROVED,
    )
    item = GrowthContentQueueItem.objects.create(
        draft=draft,
        channel_connection=connection,
        status=GrowthContentQueueItem.Status.SCHEDULED,
        scheduled_for=timezone.now() - timedelta(minutes=1),
    )
    job = GrowthScheduledPostJob.objects.create(
        queue_item=item,
        run_at=timezone.now() - timedelta(minutes=1),
    )

    counts = prepare_due_scheduled_posts()

    job.refresh_from_db()
    item.refresh_from_db()
    assert counts["ready"] == 1
    assert job.status == GrowthScheduledPostJob.Status.READY
    assert item.status == GrowthContentQueueItem.Status.SCHEDULED
    assert item.posted_at is None


@pytest.mark.django_db
def test_ready_approved_post_publishes_and_records_provider_id():
    connection = GrowthChannelConnection.objects.create(
        provider=GrowthChannelConnection.Provider.META,
        external_account_id="page-123",
        status=GrowthChannelConnection.Status.CONNECTED,
        metadata={"account_kind": "facebook_page"},
    )
    GrowthOAuthToken.objects.create(
        connection=connection,
        provider="META",
        access_token="secret-token",
        is_active=True,
    )
    draft = GrowthContentDraft.objects.create(
        title="Approved",
        body="Approved content",
        status=GrowthContentDraft.Status.APPROVED,
    )
    item = GrowthContentQueueItem.objects.create(
        draft=draft,
        channel_connection=connection,
        status=GrowthContentQueueItem.Status.SCHEDULED,
        scheduled_for=timezone.now() - timedelta(minutes=1),
    )
    job = GrowthScheduledPostJob.objects.create(
        queue_item=item,
        run_at=timezone.now() - timedelta(minutes=1),
        status=GrowthScheduledPostJob.Status.READY,
    )

    with patch(
        "platform_growth.services.runtime.publish_social_post",
        return_value=PublishResult(provider="META", external_post_id="page-123_456", raw={"id": "page-123_456"}),
    ):
        counts = publish_ready_scheduled_posts()

    job.refresh_from_db()
    item.refresh_from_db()
    assert counts["published"] == 1
    assert job.status == GrowthScheduledPostJob.Status.COMPLETED
    assert job.metadata["external_post_id"] == "page-123_456"
    assert item.status == GrowthContentQueueItem.Status.POSTED
    assert item.metadata["external_post_id"] == "page-123_456"
    assert item.posted_at is not None


@pytest.mark.django_db
def test_publish_failure_is_audited_without_marking_job_complete():
    connection = GrowthChannelConnection.objects.create(
        provider=GrowthChannelConnection.Provider.META,
        external_account_id="page-456",
        status=GrowthChannelConnection.Status.CONNECTED,
        metadata={"account_kind": "facebook_page"},
    )
    draft = GrowthContentDraft.objects.create(
        title="Approved",
        body="Approved content",
        status=GrowthContentDraft.Status.APPROVED,
    )
    item = GrowthContentQueueItem.objects.create(
        draft=draft,
        channel_connection=connection,
        status=GrowthContentQueueItem.Status.SCHEDULED,
    )
    job = GrowthScheduledPostJob.objects.create(
        queue_item=item,
        run_at=timezone.now() - timedelta(minutes=1),
        status=GrowthScheduledPostJob.Status.READY,
    )

    with patch(
        "platform_growth.services.runtime.publish_social_post",
        side_effect=SocialPublishError("Meta rejected the publishing request."),
    ):
        counts = publish_ready_scheduled_posts()

    job.refresh_from_db()
    item.refresh_from_db()
    assert counts["failed"] == 1
    assert job.status == GrowthScheduledPostJob.Status.READY
    assert job.metadata["last_publish_status"] == "FAILED"
    assert "Meta rejected" in job.last_error
    assert item.status == GrowthContentQueueItem.Status.FAILED


@pytest.mark.django_db
def test_publisher_never_sends_pending_job_even_when_draft_is_approved():
    connection = GrowthChannelConnection.objects.create(
        provider=GrowthChannelConnection.Provider.META,
        external_account_id="page-789",
        status=GrowthChannelConnection.Status.CONNECTED,
    )
    draft = GrowthContentDraft.objects.create(
        title="Approved but not ready",
        body="Must not bypass READY gate",
        status=GrowthContentDraft.Status.APPROVED,
    )
    item = GrowthContentQueueItem.objects.create(
        draft=draft,
        channel_connection=connection,
        status=GrowthContentQueueItem.Status.SCHEDULED,
    )
    GrowthScheduledPostJob.objects.create(
        queue_item=item,
        run_at=timezone.now() - timedelta(minutes=1),
        status=GrowthScheduledPostJob.Status.PENDING,
    )

    with patch("platform_growth.services.runtime.publish_social_post") as publisher:
        counts = publish_ready_scheduled_posts()

    assert counts == {"published": 0, "failed": 0, "skipped": 0}
    publisher.assert_not_called()
