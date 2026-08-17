from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests
from django.conf import settings

from platform_growth.models import GrowthChannelConnection, GrowthOAuthToken


class SocialPublishError(RuntimeError):
    """Safe provider error surfaced to the Growth runtime without leaking tokens."""


@dataclass(frozen=True)
class PublishResult:
    provider: str
    external_post_id: str
    raw: dict[str, Any]


def build_outbound_payload(message_text: str) -> dict:
    return {
        "provider": "META",
        "message": message_text,
    }


def _graph_version() -> str:
    return str(getattr(settings, "META_GRAPH_API_VERSION", "") or "v20.0").strip()


def _active_token(connection: GrowthChannelConnection) -> GrowthOAuthToken:
    token = connection.oauth_tokens.filter(provider="META", is_active=True).order_by("-created_at").first()
    if not token or not token.access_token:
        raise SocialPublishError("Connected Meta account has no active publishing token.")
    return token


def _safe_public_media_url(media_url: str | None) -> str:
    value = str(media_url or "").strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise SocialPublishError("Social media image must use a public HTTPS URL.")
    return value


def _post_graph(url: str, *, data: dict[str, Any], failure_message: str) -> dict[str, Any]:
    try:
        response = requests.post(url, data=data, timeout=20)
        payload = response.json()
    except Exception as exc:
        raise SocialPublishError(failure_message) from exc
    if not response.ok or not isinstance(payload, dict) or payload.get("error"):
        raise SocialPublishError(failure_message)
    return payload


def _validate_meta_connection(connection: GrowthChannelConnection):
    if connection.provider != GrowthChannelConnection.Provider.META:
        raise SocialPublishError("This publisher only supports Meta connections.")
    if connection.status != GrowthChannelConnection.Status.CONNECTED:
        raise SocialPublishError("Meta channel is not connected.")
    if not connection.external_account_id:
        raise SocialPublishError("Meta connection is missing its Page id.")
    if (connection.metadata or {}).get("account_kind") != "facebook_page":
        raise SocialPublishError("Meta publishing requires a connected Facebook Page.")


def publish_meta_page_post(
    *,
    connection: GrowthChannelConnection,
    message: str,
    media_url: str | None = None,
) -> PublishResult:
    _validate_meta_connection(connection)
    image_url = _safe_public_media_url(media_url)
    if not message.strip() and not image_url:
        raise SocialPublishError("Approved post has no message text or image.")

    token = _active_token(connection)
    if image_url:
        url = f"https://graph.facebook.com/{_graph_version()}/{connection.external_account_id}/photos"
        payload = _post_graph(
            url,
            data={"url": image_url, "caption": message, "access_token": token.access_token},
            failure_message="Meta rejected the Facebook image publishing request.",
        )
    else:
        url = f"https://graph.facebook.com/{_graph_version()}/{connection.external_account_id}/feed"
        payload = _post_graph(
            url,
            data={"message": message, "access_token": token.access_token},
            failure_message="Meta rejected the Facebook publishing request.",
        )

    external_post_id = str(payload.get("post_id") or payload.get("id") or "").strip()
    if not external_post_id:
        raise SocialPublishError("Meta did not return a Facebook post id.")
    return PublishResult(provider="META", external_post_id=external_post_id, raw={"id": external_post_id})


def _instagram_business_id(connection: GrowthChannelConnection) -> str:
    metadata = connection.metadata or {}
    selected = metadata.get("selected_account") or {}
    instagram = selected.get("instagram_business_account") or {}
    value = str(instagram.get("id") or metadata.get("instagram_business_account_id") or "").strip()
    if not value:
        raise SocialPublishError("Connected Meta Page has no linked Instagram Business account.")
    return value


def publish_instagram_image_post(
    *,
    connection: GrowthChannelConnection,
    message: str,
    media_url: str | None,
) -> PublishResult:
    _validate_meta_connection(connection)
    image_url = _safe_public_media_url(media_url)
    if not image_url:
        raise SocialPublishError("Instagram publishing requires a public HTTPS image URL.")

    token = _active_token(connection)
    instagram_id = _instagram_business_id(connection)
    base = f"https://graph.facebook.com/{_graph_version()}/{instagram_id}"

    container = _post_graph(
        f"{base}/media",
        data={"image_url": image_url, "caption": message, "access_token": token.access_token},
        failure_message="Meta rejected the Instagram media container request.",
    )
    creation_id = str(container.get("id") or "").strip()
    if not creation_id:
        raise SocialPublishError("Meta did not return an Instagram media container id.")

    published = _post_graph(
        f"{base}/media_publish",
        data={"creation_id": creation_id, "access_token": token.access_token},
        failure_message="Meta rejected the Instagram publish request.",
    )
    external_post_id = str(published.get("id") or "").strip()
    if not external_post_id:
        raise SocialPublishError("Meta did not return an Instagram media id.")

    return PublishResult(
        provider="INSTAGRAM",
        external_post_id=external_post_id,
        raw={"id": external_post_id, "creation_id": creation_id},
    )


def publish_social_post(
    *,
    connection: GrowthChannelConnection,
    message: str,
    target_platform: str = "facebook",
    media_url: str | None = None,
) -> PublishResult:
    target = str(target_platform or "facebook").strip().lower()
    if connection.provider != GrowthChannelConnection.Provider.META:
        raise SocialPublishError(f"Publishing is not implemented for provider '{connection.provider}'.")
    if target in {"instagram", "ig"}:
        return publish_instagram_image_post(connection=connection, message=message, media_url=media_url)
    if target in {"facebook", "fb", "meta"}:
        return publish_meta_page_post(connection=connection, message=message, media_url=media_url)
    raise SocialPublishError(f"Publishing target '{target_platform}' is not supported.")
