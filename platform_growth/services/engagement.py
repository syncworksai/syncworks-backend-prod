from __future__ import annotations

from collections import Counter
from datetime import timedelta
from typing import Any

import requests
from django.utils import timezone

from platform_growth.models import GrowthChannelConnection, GrowthContentQueueItem, GrowthOAuthToken


class EngagementSyncError(RuntimeError):
    pass


def _active_token(connection: GrowthChannelConnection) -> GrowthOAuthToken:
    token = connection.oauth_tokens.filter(is_active=True).order_by("-created_at").first()
    if not token or not token.access_token:
        raise EngagementSyncError("Connected social account has no active token.")
    return token


def _graph_version() -> str:
    from django.conf import settings

    return str(getattr(settings, "META_GRAPH_API_VERSION", "") or "v20.0").strip()


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _facebook_metrics(*, external_post_id: str, token: str) -> dict[str, Any]:
    url = f"https://graph.facebook.com/{_graph_version()}/{external_post_id}"
    response = requests.get(
        url,
        params={
            "fields": "likes.limit(0).summary(true),comments.limit(0).summary(true),shares,permalink_url,created_time",
            "access_token": token,
        },
        timeout=15,
    )
    payload = response.json()
    if not response.ok or not isinstance(payload, dict) or payload.get("error"):
        raise EngagementSyncError("Meta rejected the Facebook engagement request.")

    likes = _safe_int(((payload.get("likes") or {}).get("summary") or {}).get("total_count"))
    comments = _safe_int(((payload.get("comments") or {}).get("summary") or {}).get("total_count"))
    shares = _safe_int((payload.get("shares") or {}).get("count"))
    return {
        "likes": likes,
        "comments": comments,
        "shares": shares,
        "total_engagement": likes + comments + shares,
        "permalink": payload.get("permalink_url") or "",
        "provider_created_time": payload.get("created_time") or "",
    }


def _instagram_metrics(*, external_post_id: str, token: str) -> dict[str, Any]:
    url = f"https://graph.facebook.com/{_graph_version()}/{external_post_id}"
    response = requests.get(
        url,
        params={
            "fields": "like_count,comments_count,media_type,permalink,timestamp",
            "access_token": token,
        },
        timeout=15,
    )
    payload = response.json()
    if not response.ok or not isinstance(payload, dict) or payload.get("error"):
        raise EngagementSyncError("Meta rejected the Instagram engagement request.")

    likes = _safe_int(payload.get("like_count"))
    comments = _safe_int(payload.get("comments_count"))
    return {
        "likes": likes,
        "comments": comments,
        "shares": 0,
        "total_engagement": likes + comments,
        "permalink": payload.get("permalink") or "",
        "media_type": payload.get("media_type") or "",
        "provider_created_time": payload.get("timestamp") or "",
    }


def fetch_post_engagement(item: GrowthContentQueueItem) -> dict[str, Any]:
    connection = item.channel_connection
    metadata = dict(item.metadata or {})
    external_post_id = str(metadata.get("external_post_id") or "").strip()
    if not external_post_id:
        raise EngagementSyncError("Posted item has no provider post id.")

    token = _active_token(connection).access_token
    if connection.provider == GrowthChannelConnection.Provider.INSTAGRAM:
        return _instagram_metrics(external_post_id=external_post_id, token=token)
    if connection.provider == GrowthChannelConnection.Provider.META:
        return _facebook_metrics(external_post_id=external_post_id, token=token)
    raise EngagementSyncError("Engagement sync is not implemented for this provider.")


def refresh_posted_engagement(*, user=None, limit=50, now=None) -> dict[str, int]:
    now = now or timezone.now()
    qs = GrowthContentQueueItem.objects.select_related("channel_connection").filter(
        status=GrowthContentQueueItem.Status.POSTED,
        posted_at__gte=now - timedelta(days=30),
    ).order_by("-posted_at", "-id")
    if user is not None:
        qs = qs.filter(created_by=user)

    counts = {"updated": 0, "failed": 0, "skipped": 0}
    for item in qs[: max(1, limit)]:
        metadata = dict(item.metadata or {})
        last_sync_raw = metadata.get("engagement_synced_at")
        if last_sync_raw:
            from django.utils.dateparse import parse_datetime

            parsed = parse_datetime(str(last_sync_raw))
            if parsed and parsed > now - timedelta(minutes=30):
                counts["skipped"] += 1
                continue

        try:
            metrics = fetch_post_engagement(item)
        except EngagementSyncError as exc:
            metadata["engagement_last_error"] = str(exc)
            metadata["engagement_synced_at"] = now.isoformat()
            item.metadata = metadata
            item.save(update_fields=["metadata", "updated_at"])
            counts["failed"] += 1
            continue

        metadata["engagement"] = metrics
        metadata["engagement_synced_at"] = now.isoformat()
        metadata.pop("engagement_last_error", None)
        item.metadata = metadata
        item.save(update_fields=["metadata", "updated_at"])
        counts["updated"] += 1

    return counts


def growth_intelligence_for_user(user) -> dict[str, Any]:
    items = list(
        GrowthContentQueueItem.objects.select_related("draft", "channel_connection")
        .filter(created_by=user, status=GrowthContentQueueItem.Status.POSTED)
        .order_by("-posted_at", "-id")[:100]
    )

    total_engagement = 0
    provider_counts: Counter[str] = Counter()
    ranked = []
    for item in items:
        metadata = item.metadata or {}
        engagement = metadata.get("engagement") or {}
        score = _safe_int(engagement.get("total_engagement"))
        total_engagement += score
        provider = str(metadata.get("target_platform") or item.channel_connection.provider or "UNKNOWN").upper()
        provider_counts[provider] += 1
        ranked.append(
            {
                "queue_item_id": item.id,
                "draft_id": item.draft_id,
                "title": item.draft.title,
                "provider": provider,
                "posted_at": item.posted_at.isoformat() if item.posted_at else None,
                "engagement": {
                    "likes": _safe_int(engagement.get("likes")),
                    "comments": _safe_int(engagement.get("comments")),
                    "shares": _safe_int(engagement.get("shares")),
                    "total": score,
                },
                "permalink": engagement.get("permalink") or "",
            }
        )

    ranked.sort(key=lambda row: (row["engagement"]["total"], row.get("posted_at") or ""), reverse=True)
    top_posts = ranked[:5]
    average = round(total_engagement / len(items), 2) if items else 0

    recommendations = []
    if not items:
        recommendations.append({"priority": 1, "code": "POST_FIRST_CONTENT", "message": "Publish approved content to begin measuring what your audience responds to."})
    elif top_posts and top_posts[0]["engagement"]["total"] > average:
        recommendations.append({"priority": 1, "code": "REUSE_WINNER", "message": f"'{top_posts[0]['title']}' is outperforming your average. Reuse its topic or format in the next content cycle."})
    if len(items) >= 3 and average < 2:
        recommendations.append({"priority": 2, "code": "LOW_ENGAGEMENT", "message": "Recent posts are getting limited engagement. Test a clearer hook, local proof, before/after media, or a direct customer question."})
    if provider_counts and len(provider_counts) == 1:
        only_provider = next(iter(provider_counts))
        recommendations.append({"priority": 3, "code": "CHANNEL_DIVERSITY", "message": f"Your measured content is concentrated on {only_provider}. Connect and test another supported channel if it fits your audience."})

    return {
        "posted_count": len(items),
        "total_engagement": total_engagement,
        "average_engagement_per_post": average,
        "providers": dict(provider_counts),
        "top_posts": top_posts,
        "recommendations": recommendations[:5],
    }
