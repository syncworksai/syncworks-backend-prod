from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from platform_growth.models import (
    GrowthAutomationRecipe,
    GrowthChannelConnection,
    GrowthContentDraft,
    GrowthContentQueueItem,
    GrowthScheduledPostJob,
    PlatformLead,
)
from platform_growth.services.posting import SocialPublishError, publish_social_post


@dataclass(frozen=True)
class RuntimeResult:
    status: str
    message: str
    data: dict


def _next_run(recipe: GrowthAutomationRecipe, now):
    schedule = recipe.recipe.get("schedule") or {}
    minutes = max(15, int(schedule.get("interval_minutes") or 60))
    return now + timedelta(minutes=minutes)


def recipe_is_due(recipe: GrowthAutomationRecipe, now=None) -> bool:
    now = now or timezone.now()
    value = (recipe.metadata or {}).get("next_run_at")
    if not value:
        return True
    parsed = parse_datetime(str(value))
    return not parsed or parsed <= now


def _create_social_draft(recipe: GrowthAutomationRecipe) -> RuntimeResult:
    config = recipe.recipe or {}
    template = config.get("template") or {}
    title = str(template.get("title") or "Scheduled social draft").strip()
    body = str(template.get("body") or "").strip()
    if not body:
        return RuntimeResult("SKIPPED", "No approved template body configured.", {})

    draft = GrowthContentDraft.objects.create(
        title=title[:180],
        body=body,
        source="BOT_RUNTIME",
        status=GrowthContentDraft.Status.DRAFT,
        created_by=recipe.created_by,
        metadata={
            "automation_recipe_id": recipe.id,
            "bot_key": config.get("bot_key", "content_calendar"),
            "requires_approval": True,
            "target_platform": str(config.get("target_platform") or "facebook").lower(),
            "media_url": str(template.get("media_url") or "").strip(),
        },
    )
    return RuntimeResult(
        "COMPLETED",
        "Created an approval-required social draft.",
        {"draft_id": draft.id, "outbound_sent": False},
    )


def _create_lead_follow_up_drafts(recipe: GrowthAutomationRecipe) -> RuntimeResult:
    config = recipe.recipe or {}
    age_hours = max(1, int(config.get("lead_age_hours") or 24))
    limit = min(25, max(1, int(config.get("max_items_per_run") or 10)))
    cutoff = timezone.now() - timedelta(hours=age_hours)

    leads = PlatformLead.objects.filter(
        status__in=[PlatformLead.Status.NEW, PlatformLead.Status.QUALIFIED],
        last_activity_at__lte=cutoff,
    )
    if recipe.created_by_id:
        leads = leads.filter(assigned_to=recipe.created_by)
    leads = leads.order_by("last_activity_at", "id")[:limit]

    created = []
    for lead in leads:
        exists = GrowthContentDraft.objects.filter(
            source="BOT_RUNTIME",
            created_by=recipe.created_by,
            metadata__bot_key="lead_follow_up",
            metadata__lead_id=lead.id,
            status__in=[
                GrowthContentDraft.Status.DRAFT,
                GrowthContentDraft.Status.READY,
                GrowthContentDraft.Status.APPROVED,
            ],
        ).exists()
        if exists:
            continue
        name = (lead.full_name or "there").strip() or "there"
        draft = GrowthContentDraft.objects.create(
            title=f"Follow up: {name}"[:180],
            body=f"Hi {name}, just following up to see if we can help with what you need.",
            source="BOT_RUNTIME",
            status=GrowthContentDraft.Status.DRAFT,
            created_by=recipe.created_by,
            metadata={
                "automation_recipe_id": recipe.id,
                "bot_key": "lead_follow_up",
                "lead_id": lead.id,
                "requires_approval": True,
            },
        )
        created.append(draft.id)

    return RuntimeResult(
        "COMPLETED",
        f"Prepared {len(created)} approval-required lead follow-up draft(s).",
        {"draft_ids": created, "outbound_sent": False},
    )


HANDLERS: dict[str, Callable[[GrowthAutomationRecipe], RuntimeResult]] = {
    "content_calendar": _create_social_draft,
    "lead_follow_up": _create_lead_follow_up_drafts,
}


def run_recipe(recipe: GrowthAutomationRecipe, *, force=False, now=None) -> RuntimeResult:
    now = now or timezone.now()
    if not recipe.is_active:
        return RuntimeResult("SKIPPED", "Recipe is disabled.", {})
    if not force and not recipe_is_due(recipe, now=now):
        return RuntimeResult("SKIPPED", "Recipe is not due yet.", {})

    bot_key = str((recipe.recipe or {}).get("bot_key") or "").strip()
    handler = HANDLERS.get(bot_key)
    if not handler:
        result = RuntimeResult("SKIPPED", f"No runtime handler registered for '{bot_key}'.", {})
    else:
        try:
            result = handler(recipe)
        except Exception as exc:
            result = RuntimeResult("FAILED", str(exc), {})

    metadata = dict(recipe.metadata or {})
    metadata.update(
        {
            "last_runtime_status": result.status,
            "last_runtime_message": result.message,
            "last_runtime_result": result.data,
            "last_runtime_at": now.isoformat(),
            "next_run_at": _next_run(recipe, now).isoformat(),
        }
    )
    recipe.last_run_at = now
    recipe.metadata = metadata
    recipe.save(update_fields=["last_run_at", "metadata", "updated_at"])
    return result


def prepare_due_scheduled_posts(*, limit=50, now=None) -> dict:
    """Move due jobs to READY only after explicit approval and channel validation."""
    now = now or timezone.now()
    counts = {"ready": 0, "skipped": 0}
    ids = list(
        GrowthScheduledPostJob.objects.filter(
            status=GrowthScheduledPostJob.Status.PENDING,
            run_at__lte=now,
        )
        .order_by("run_at", "id")
        .values_list("id", flat=True)[:limit]
    )

    for job_id in ids:
        with transaction.atomic():
            job = (
                GrowthScheduledPostJob.objects.select_for_update()
                .select_related("queue_item__draft", "queue_item__channel_connection")
                .get(id=job_id)
            )
            if job.status != GrowthScheduledPostJob.Status.PENDING or job.run_at > now:
                counts["skipped"] += 1
                continue

            item = job.queue_item
            approved = item.draft.status == GrowthContentDraft.Status.APPROVED
            connected = item.channel_connection.status == GrowthChannelConnection.Status.CONNECTED
            if not approved or not connected:
                job.attempts += 1
                job.last_attempt_at = now
                reasons = []
                if not approved:
                    reasons.append("draft is not approved")
                if not connected:
                    reasons.append("channel is not connected")
                job.last_error = "; ".join(reasons)
                job.save(update_fields=["attempts", "last_attempt_at", "last_error", "updated_at"])
                counts["skipped"] += 1
                continue

            job.status = GrowthScheduledPostJob.Status.READY
            job.last_error = ""
            job.save(update_fields=["status", "last_error", "updated_at"])
            counts["ready"] += 1

    return counts


def _publish_target(item: GrowthContentQueueItem) -> tuple[str, str]:
    draft_metadata = item.draft.metadata or {}
    item_metadata = item.metadata or {}
    target_platform = str(
        item_metadata.get("target_platform")
        or draft_metadata.get("target_platform")
        or "facebook"
    ).strip().lower()
    media_url = str(
        item_metadata.get("media_url")
        or draft_metadata.get("media_url")
        or draft_metadata.get("image_url")
        or ""
    ).strip()
    return target_platform, media_url


def publish_ready_scheduled_posts(*, limit=25, now=None) -> dict:
    """Publish READY jobs through provider adapters and record auditable outcomes.

    READY is the hard approval boundary. This function never considers PENDING jobs,
    so unattended publishing cannot bypass the approval gate in prepare_due_scheduled_posts.
    """
    now = now or timezone.now()
    counts = {"published": 0, "failed": 0, "skipped": 0}
    ids = list(
        GrowthScheduledPostJob.objects.filter(status=GrowthScheduledPostJob.Status.READY)
        .order_by("run_at", "id")
        .values_list("id", flat=True)[:limit]
    )

    for job_id in ids:
        with transaction.atomic():
            job = (
                GrowthScheduledPostJob.objects.select_for_update()
                .select_related("queue_item__draft", "queue_item__channel_connection")
                .get(id=job_id)
            )
            if job.status != GrowthScheduledPostJob.Status.READY:
                counts["skipped"] += 1
                continue

            item = job.queue_item
            draft = item.draft
            connection = item.channel_connection
            if draft.status != GrowthContentDraft.Status.APPROVED or connection.status != GrowthChannelConnection.Status.CONNECTED:
                job.attempts += 1
                job.last_attempt_at = now
                job.last_error = "Approval or connection changed before publish."
                job.save(update_fields=["attempts", "last_attempt_at", "last_error", "updated_at"])
                counts["failed"] += 1
                continue

            target_platform, media_url = _publish_target(item)
            job.attempts += 1
            job.last_attempt_at = now
            try:
                result = publish_social_post(
                    connection=connection,
                    message=draft.body,
                    target_platform=target_platform,
                    media_url=media_url,
                )
            except SocialPublishError as exc:
                job.last_error = str(exc)
                metadata = dict(job.metadata or {})
                metadata.update({
                    "last_publish_status": "FAILED",
                    "last_publish_at": now.isoformat(),
                    "target_platform": target_platform,
                })
                job.metadata = metadata
                job.save(update_fields=["attempts", "last_attempt_at", "last_error", "metadata", "updated_at"])
                item.status = GrowthContentQueueItem.Status.FAILED
                item.fail_reason = str(exc)
                item.save(update_fields=["status", "fail_reason", "updated_at"])
                counts["failed"] += 1
                continue

            item.status = GrowthContentQueueItem.Status.POSTED
            item.posted_at = now
            item.fail_reason = ""
            item_metadata = dict(item.metadata or {})
            item_metadata.update({
                "provider": result.provider,
                "target_platform": target_platform,
                "external_post_id": result.external_post_id,
                "published_at": now.isoformat(),
            })
            item.metadata = item_metadata
            item.save(update_fields=["status", "posted_at", "fail_reason", "metadata", "updated_at"])

            job.status = GrowthScheduledPostJob.Status.COMPLETED
            job.last_error = ""
            job_metadata = dict(job.metadata or {})
            job_metadata.update({
                "publish_status": "COMPLETED",
                "provider": result.provider,
                "target_platform": target_platform,
                "external_post_id": result.external_post_id,
                "published_at": now.isoformat(),
            })
            job.metadata = job_metadata
            job.save(update_fields=["status", "attempts", "last_attempt_at", "last_error", "metadata", "updated_at"])
            counts["published"] += 1

    return counts


def run_due_recipes(*, limit=100, now=None) -> list[tuple[int, RuntimeResult]]:
    now = now or timezone.now()
    recipes = GrowthAutomationRecipe.objects.filter(is_active=True).order_by("id")[:limit]
    output = []
    for recipe in recipes:
        if recipe_is_due(recipe, now=now):
            output.append((recipe.id, run_recipe(recipe, now=now)))
    return output
