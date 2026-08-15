from datetime import timedelta

import pytest
from django.utils import timezone

from platform_growth.models import (
    GrowthAutomationRecipe,
    GrowthChannelConnection,
    GrowthContentDraft,
    GrowthContentQueueItem,
    GrowthScheduledPostJob,
)
from platform_growth.services.runtime import prepare_due_scheduled_posts, run_recipe


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
