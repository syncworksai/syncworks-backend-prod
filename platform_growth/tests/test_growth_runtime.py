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
from platform_growth.services.posting import PublishResult, SocialPublishError, publish_instagram_image_post
from platform_growth.services.runtime import (
    prepare_due_scheduled_posts,
    publish_ready_scheduled_posts,
    run_recipe,
)


@pytest.fixture(autouse=True)
def isolate_growth_runtime_rows():
    GrowthScheduledPostJob.objects.all().delete()
    GrowthContentQueueItem.objects.all().delete()
    GrowthOAuthToken.objects.all().delete()
    GrowthContentDraft.objects.all().delete()
    GrowthChannelConnection.objects.all().delete()
    GrowthAutomationRecipe.objects.all().delete()
    yield
    GrowthScheduledPostJob.objects.all().delete()
    GrowthContentQueueItem.objects.all().delete()
    GrowthOAuthToken.objects.all().delete()
    GrowthContentDraft.objects.all().delete()
    GrowthChannelConnection.objects.all().delete()
    GrowthAutomationRecipe.objects.all().delete()


@pytest.mark.django_db
def test_content_calendar_bot_creates_draft_without_sending():
    recipe = GrowthAutomationRecipe.objects.create(
        name="Content Calendar Bot",
        trigger_type="SCHEDULED",
        recipe={
            "bot_key": "content_calendar",
            "schedule": {"interval_minutes": 60},
            "target_platform": "instagram",
            "template": {
                "title": "Tip",
                "body": "Helpful business tip.",
                "media_url": "https://cdn.example.com/tip.jpg",
            },
        },
    )
    result = run_recipe(recipe, force=True)
    assert result.status == "COMPLETED"
    assert result.data["outbound_sent"] is False
    draft = GrowthContentDraft.objects.get(id=result.data["draft_id"])
    assert draft.status == GrowthContentDraft.Status.DRAFT
    assert draft.metadata["requires_approval"] is True
    assert draft.metadata["target_platform"] == "instagram"
    assert draft.metadata["media_url"] == "https://cdn.example.com/tip.jpg"


@pytest.mark.django_db
def test_scheduled_post_does_not_become_ready_without_approval():
    connection = GrowthChannelConnection.objects.create(provider=GrowthChannelConnection.Provider.META, external_account_id="runtime-acct-1", status=GrowthChannelConnection.Status.CONNECTED)
    draft = GrowthContentDraft.objects.create(title="Pending approval", body="Do not send yet", status=GrowthContentDraft.Status.DRAFT)
    item = GrowthContentQueueItem.objects.create(draft=draft, channel_connection=connection, status=GrowthContentQueueItem.Status.SCHEDULED, scheduled_for=timezone.now() - timedelta(minutes=1))
    job = GrowthScheduledPostJob.objects.create(queue_item=item, run_at=timezone.now() - timedelta(minutes=1))
    counts = prepare_due_scheduled_posts()
    job.refresh_from_db()
    assert counts["ready"] == 0
    assert job.status == GrowthScheduledPostJob.Status.PENDING
    assert "not approved" in job.last_error


@pytest.mark.django_db
def test_approved_post_with_connected_channel_becomes_ready_not_published():
    connection = GrowthChannelConnection.objects.create(provider=GrowthChannelConnection.Provider.META, external_account_id="runtime-acct-2", status=GrowthChannelConnection.Status.CONNECTED)
    draft = GrowthContentDraft.objects.create(title="Approved", body="Approved content", status=GrowthContentDraft.Status.APPROVED)
    item = GrowthContentQueueItem.objects.create(draft=draft, channel_connection=connection, status=GrowthContentQueueItem.Status.SCHEDULED, scheduled_for=timezone.now() - timedelta(minutes=1))
    job = GrowthScheduledPostJob.objects.create(queue_item=item, run_at=timezone.now() - timedelta(minutes=1))
    counts = prepare_due_scheduled_posts()
    job.refresh_from_db()
    item.refresh_from_db()
    assert counts["ready"] == 1
    assert job.status == GrowthScheduledPostJob.Status.READY
    assert item.status == GrowthContentQueueItem.Status.SCHEDULED
    assert item.posted_at is None


@pytest.mark.django_db
def test_ready_approved_facebook_post_publishes_and_records_provider_id():
    connection = GrowthChannelConnection.objects.create(provider=GrowthChannelConnection.Provider.META, external_account_id="runtime-page-publish", status=GrowthChannelConnection.Status.CONNECTED, metadata={"account_kind": "facebook_page"})
    GrowthOAuthToken.objects.create(connection=connection, provider="META", access_token="secret-token", is_active=True)
    draft = GrowthContentDraft.objects.create(title="Approved", body="Approved content", status=GrowthContentDraft.Status.APPROVED)
    item = GrowthContentQueueItem.objects.create(draft=draft, channel_connection=connection, status=GrowthContentQueueItem.Status.SCHEDULED, scheduled_for=timezone.now() - timedelta(minutes=1))
    job = GrowthScheduledPostJob.objects.create(queue_item=item, run_at=timezone.now() - timedelta(minutes=1), status=GrowthScheduledPostJob.Status.READY)
    with patch("platform_growth.services.runtime.publish_social_post", return_value=PublishResult(provider="META", external_post_id="runtime-page-publish_456", raw={"id": "runtime-page-publish_456"})) as publisher:
        counts = publish_ready_scheduled_posts()
    publisher.assert_called_once_with(connection=connection, message="Approved content", target_platform="facebook", media_url="")
    job.refresh_from_db()
    item.refresh_from_db()
    assert counts["published"] == 1
    assert job.status == GrowthScheduledPostJob.Status.COMPLETED
    assert job.metadata["target_platform"] == "facebook"
    assert item.status == GrowthContentQueueItem.Status.POSTED


@pytest.mark.django_db
def test_ready_instagram_job_routes_media_and_records_target():
    connection = GrowthChannelConnection.objects.create(provider=GrowthChannelConnection.Provider.META, external_account_id="runtime-page-ig", status=GrowthChannelConnection.Status.CONNECTED, metadata={"account_kind": "facebook_page", "selected_account": {"instagram_business_account": {"id": "ig-runtime"}}})
    GrowthOAuthToken.objects.create(connection=connection, provider="META", access_token="secret-token", is_active=True)
    draft = GrowthContentDraft.objects.create(title="IG post", body="Instagram caption", status=GrowthContentDraft.Status.APPROVED, metadata={"target_platform": "instagram", "media_url": "https://cdn.example.com/post.jpg"})
    item = GrowthContentQueueItem.objects.create(draft=draft, channel_connection=connection, status=GrowthContentQueueItem.Status.SCHEDULED)
    job = GrowthScheduledPostJob.objects.create(queue_item=item, run_at=timezone.now() - timedelta(minutes=1), status=GrowthScheduledPostJob.Status.READY)
    with patch("platform_growth.services.runtime.publish_social_post", return_value=PublishResult(provider="INSTAGRAM", external_post_id="ig-media-1", raw={"id": "ig-media-1"})) as publisher:
        counts = publish_ready_scheduled_posts()
    publisher.assert_called_once_with(connection=connection, message="Instagram caption", target_platform="instagram", media_url="https://cdn.example.com/post.jpg")
    job.refresh_from_db()
    item.refresh_from_db()
    assert counts["published"] == 1
    assert job.metadata["target_platform"] == "instagram"
    assert item.metadata["target_platform"] == "instagram"
    assert item.metadata["provider"] == "INSTAGRAM"


@pytest.mark.django_db
def test_instagram_adapter_creates_container_then_publishes():
    connection = GrowthChannelConnection.objects.create(provider=GrowthChannelConnection.Provider.META, external_account_id="runtime-page-ig-adapter", status=GrowthChannelConnection.Status.CONNECTED, metadata={"account_kind": "facebook_page", "selected_account": {"instagram_business_account": {"id": "ig-123"}}})
    GrowthOAuthToken.objects.create(connection=connection, provider="META", access_token="secret-token", is_active=True)

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload
            self.ok = True
        def json(self):
            return self.payload

    with patch("platform_growth.services.posting.requests.post", side_effect=[FakeResponse({"id": "container-1"}), FakeResponse({"id": "media-1"})]) as post:
        result = publish_instagram_image_post(connection=connection, message="Caption", media_url="https://cdn.example.com/image.jpg")
    assert result.provider == "INSTAGRAM"
    assert result.external_post_id == "media-1"
    assert post.call_count == 2
    assert post.call_args_list[0].args[0].endswith("/ig-123/media")
    assert post.call_args_list[1].args[0].endswith("/ig-123/media_publish")


@pytest.mark.django_db
def test_instagram_requires_public_https_media():
    connection = GrowthChannelConnection.objects.create(provider=GrowthChannelConnection.Provider.META, external_account_id="runtime-page-ig-bad", status=GrowthChannelConnection.Status.CONNECTED, metadata={"account_kind": "facebook_page", "selected_account": {"instagram_business_account": {"id": "ig-bad"}}})
    GrowthOAuthToken.objects.create(connection=connection, provider="META", access_token="secret-token", is_active=True)
    with pytest.raises(SocialPublishError, match="public HTTPS"):
        publish_instagram_image_post(connection=connection, message="Caption", media_url="http://local/image.jpg")


@pytest.mark.django_db
def test_publish_failure_is_audited_without_marking_job_complete():
    connection = GrowthChannelConnection.objects.create(provider=GrowthChannelConnection.Provider.META, external_account_id="runtime-page-failure", status=GrowthChannelConnection.Status.CONNECTED, metadata={"account_kind": "facebook_page"})
    draft = GrowthContentDraft.objects.create(title="Approved", body="Approved content", status=GrowthContentDraft.Status.APPROVED)
    item = GrowthContentQueueItem.objects.create(draft=draft, channel_connection=connection, status=GrowthContentQueueItem.Status.SCHEDULED)
    job = GrowthScheduledPostJob.objects.create(queue_item=item, run_at=timezone.now() - timedelta(minutes=1), status=GrowthScheduledPostJob.Status.READY)
    with patch("platform_growth.services.runtime.publish_social_post", side_effect=SocialPublishError("Meta rejected the publishing request.")):
        counts = publish_ready_scheduled_posts()
    job.refresh_from_db()
    item.refresh_from_db()
    assert counts["failed"] == 1
    assert job.status == GrowthScheduledPostJob.Status.READY
    assert job.metadata["last_publish_status"] == "FAILED"
    assert item.status == GrowthContentQueueItem.Status.FAILED


@pytest.mark.django_db
def test_publisher_never_sends_pending_job_even_when_draft_is_approved():
    connection = GrowthChannelConnection.objects.create(provider=GrowthChannelConnection.Provider.META, external_account_id="runtime-page-pending", status=GrowthChannelConnection.Status.CONNECTED)
    draft = GrowthContentDraft.objects.create(title="Approved but not ready", body="Must not bypass READY gate", status=GrowthContentDraft.Status.APPROVED)
    item = GrowthContentQueueItem.objects.create(draft=draft, channel_connection=connection, status=GrowthContentQueueItem.Status.SCHEDULED)
    GrowthScheduledPostJob.objects.create(queue_item=item, run_at=timezone.now() - timedelta(minutes=1), status=GrowthScheduledPostJob.Status.PENDING)
    with patch("platform_growth.services.runtime.publish_social_post") as publisher:
        counts = publish_ready_scheduled_posts()
    assert counts == {"published": 0, "failed": 0, "skipped": 0}
    publisher.assert_not_called()
