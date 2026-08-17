from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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


def publish_meta_page_post(*, connection: GrowthChannelConnection, message: str) -> PublishResult:
    if connection.provider != GrowthChannelConnection.Provider.META:
        raise SocialPublishError("This publisher only supports Meta connections.")
    if connection.status != GrowthChannelConnection.Status.CONNECTED:
        raise SocialPublishError("Meta channel is not connected.")
    if not connection.external_account_id:
        raise SocialPublishError("Meta connection is missing its Page id.")
    if (connection.metadata or {}).get("account_kind") != "facebook_page":
        raise SocialPublishError("Meta publishing requires a connected Facebook Page.")
    if not message.strip():
        raise SocialPublishError("Approved post has no message text.")

    token = _active_token(connection)
    url = f"https://graph.facebook.com/{_graph_version()}/{connection.external_account_id}/feed"
    try:
        response = requests.post(
            url,
            data={"message": message, "access_token": token.access_token},
            timeout=15,
        )
        payload = response.json()
    except Exception as exc:
        raise SocialPublishError("Meta publishing request failed.") from exc

    if not response.ok or not isinstance(payload, dict) or payload.get("error"):
        raise SocialPublishError("Meta rejected the publishing request.")

    external_post_id = str(payload.get("id") or "").strip()
    if not external_post_id:
        raise SocialPublishError("Meta did not return a post id.")

    return PublishResult(
        provider="META",
        external_post_id=external_post_id,
        raw={"id": external_post_id},
    )


def publish_social_post(*, connection: GrowthChannelConnection, message: str) -> PublishResult:
    if connection.provider == GrowthChannelConnection.Provider.META:
        return publish_meta_page_post(connection=connection, message=message)
    raise SocialPublishError(f"Publishing is not implemented for provider '{connection.provider}'.")
