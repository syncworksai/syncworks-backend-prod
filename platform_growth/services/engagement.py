from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta
from typing import Any

import requests
from django.utils import timezone

from platform_growth.models import GrowthChannelConnection, GrowthContentQueueItem, GrowthOAuthToken, PlatformLead


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


def _target_platform(item: GrowthContentQueueItem) -> str:
    metadata = item.metadata or {}
    target = str(metadata.get("target_platform") or metadata.get("provider") or item.channel_connection.provider or "").strip().lower()
    if target in {"instagram", "ig"}:
        return "instagram"
    return "facebook"


def fetch_post_engagement(item: GrowthContentQueueItem) -> dict[str, Any]:
    connection = item.channel_connection
    metadata = dict(item.metadata or {})
    external_post_id = str(metadata.get("external_post_id") or "").strip()
    if not external_post_id:
        raise EngagementSyncError("Posted item has no provider post id.")

    token = _active_token(connection).access_token
    if _target_platform(item) == "instagram":
        return _instagram_metrics(external_post_id=external_post_id, token=token)
    return _facebook_metrics(external_post_id=external_post_id, token=token)


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


def _lead_attribution(user):
    by_post: dict[str, dict[str, int]] = defaultdict(lambda: {"leads": 0, "wins": 0})
    total_social = 0
    unattributed = 0
    leads = PlatformLead.objects.filter(assigned_to=user, source="META")
    for lead in leads:
        total_social += 1
        source_post_id = str((lead.metadata or {}).get("source_post_id") or "").strip()
        if not source_post_id:
            unattributed += 1
            continue
        by_post[source_post_id]["leads"] += 1
        if lead.status == PlatformLead.Status.WON:
            by_post[source_post_id]["wins"] += 1
    return by_post, total_social, unattributed


def growth_intelligence_for_user(user) -> dict[str, Any]:
    items = list(
        GrowthContentQueueItem.objects.select_related("draft", "channel_connection")
        .filter(created_by=user, status=GrowthContentQueueItem.Status.POSTED)
        .order_by("-posted_at", "-id")[:100]
    )

    attribution, total_social_leads, unattributed_social_leads = _lead_attribution(user)
    total_engagement = 0
    total_attributed_leads = 0
    total_wins = 0
    provider_counts: Counter[str] = Counter()
    ranked = []

    for item in items:
        metadata = item.metadata or {}
        engagement = metadata.get("engagement") or {}
        engagement_score = _safe_int(engagement.get("total_engagement"))
        external_post_id = str(metadata.get("external_post_id") or "").strip()
        lead_counts = attribution.get(external_post_id, {"leads": 0, "wins": 0})
        attributed_leads = _safe_int(lead_counts.get("leads"))
        wins = _safe_int(lead_counts.get("wins"))
        impact_score = engagement_score + (attributed_leads * 5) + (wins * 20)

        total_engagement += engagement_score
        total_attributed_leads += attributed_leads
        total_wins += wins
        provider = _target_platform(item).upper()
        provider_counts[provider] += 1
        ranked.append(
            {
                "queue_item_id": item.id,
                "draft_id": item.draft_id,
                "title": item.draft.title,
                "provider": provider,
                "posted_at": item.posted_at.isoformat() if item.posted_at else None,
                "external_post_id": external_post_id,
                "engagement": {
                    "likes": _safe_int(engagement.get("likes")),
                    "comments": _safe_int(engagement.get("comments")),
                    "shares": _safe_int(engagement.get("shares")),
                    "total": engagement_score,
                },
                "attribution": {"leads": attributed_leads, "wins": wins},
                "impact_score": impact_score,
                "permalink": engagement.get("permalink") or "",
            }
        )

    ranked.sort(key=lambda row: (row["impact_score"], row["engagement"]["total"], row.get("posted_at") or ""), reverse=True)
    top_posts = ranked[:5]
    average = round(total_engagement / len(items), 2) if items else 0

    recommendations = []
    if not items:
        recommendations.append({"priority": 1, "code": "POST_FIRST_CONTENT", "message": "Publish approved content to begin measuring what your audience responds to."})
    elif top_posts:
        best = top_posts[0]
        if best["attribution"]["wins"]:
            recommendations.append({"priority": 1, "code": "REUSE_CONVERTER", "message": f"'{best['title']}' has produced a won social lead. Reuse its topic, proof, and call-to-action in the next content cycle."})
        elif best["attribution"]["leads"]:
            recommendations.append({"priority": 1, "code": "REUSE_LEAD_DRIVER", "message": f"'{best['title']}' is generating attributed leads. Build the next post around the same customer intent and follow up quickly."})
        elif best["engagement"]["total"] > average:
            recommendations.append({"priority": 1, "code": "REUSE_WINNER", "message": f"'{best['title']}' is outperforming your engagement average. Reuse its topic or format and strengthen the call-to-action."})

    high_engagement_no_leads = next((row for row in ranked if row["engagement"]["total"] >= max(3, average) and row["attribution"]["leads"] == 0), None)
    if high_engagement_no_leads:
        recommendations.append({"priority": 2, "code": "ENGAGEMENT_NO_LEADS", "message": f"'{high_engagement_no_leads['title']}' gets attention but no attributed leads yet. Test a clearer request, booking link, or direct question."})
    if total_attributed_leads and not total_wins:
        recommendations.append({"priority": 2, "code": "LEADS_NO_WINS", "message": "Social is producing attributed leads but none are marked won yet. Prioritize follow-up speed and update lead outcomes so SyncWorks can learn the conversion pattern."})
    if len(items) >= 3 and average < 2:
        recommendations.append({"priority": 3, "code": "LOW_ENGAGEMENT", "message": "Recent posts are getting limited engagement. Test a clearer hook, local proof, before/after media, or a direct customer question."})
    if provider_counts and len(provider_counts) == 1:
        only_provider = next(iter(provider_counts))
        recommendations.append({"priority": 4, "code": "CHANNEL_DIVERSITY", "message": f"Your measured content is concentrated on {only_provider}. Test the other connected Meta channel when the content fits."})

    return {
        "posted_count": len(items),
        "total_engagement": total_engagement,
        "average_engagement_per_post": average,
        "attributed_leads": total_attributed_leads,
        "won_leads": total_wins,
        "social_leads_total": total_social_leads,
        "unattributed_social_leads": unattributed_social_leads,
        "providers": dict(provider_counts),
        "impact_score_formula": "engagement + (attributed leads × 5) + (won leads × 20)",
        "top_posts": top_posts,
        "recommendations": recommendations[:5],
    }
