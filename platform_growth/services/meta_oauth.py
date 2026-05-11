from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.utils import timezone


class MetaOAuthConfigurationError(ValueError):
    """Raised when required Meta OAuth settings are missing."""


class MetaOAuthRequestError(RuntimeError):
    """Raised when Meta Graph returns an unusable response."""


@dataclass(frozen=True)
class MetaOAuthConfig:
    app_id: str
    app_secret: str
    graph_api_version: str
    redirect_uri: str
    scopes: list[str]

    @property
    def scope_string(self) -> str:
        return ",".join(self.scopes)


@dataclass(frozen=True)
class MetaOAuthAccount:
    external_account_id: str
    account_label: str
    access_token: str
    metadata: dict[str, Any]


def _setting(name: str) -> str:
    return str(getattr(settings, name, "") or "").strip()


def _configured_scopes() -> list[str]:
    raw = _setting("META_OAUTH_SCOPES")
    return [scope.strip() for scope in raw.split(",") if scope.strip()]


def get_meta_oauth_config(*, require_secret: bool = False) -> MetaOAuthConfig:
    app_id = _setting("META_APP_ID")
    app_secret = _setting("META_APP_SECRET")
    graph_api_version = _setting("META_GRAPH_API_VERSION") or "v20.0"
    redirect_uri = _setting("META_OAUTH_REDIRECT_URI")
    scopes = _configured_scopes()

    missing = []
    if not app_id:
        missing.append("META_APP_ID")
    if require_secret and not app_secret:
        missing.append("META_APP_SECRET")
    if not redirect_uri:
        missing.append("META_OAUTH_REDIRECT_URI")
    if not scopes:
        missing.append("META_OAUTH_SCOPES")

    if missing:
        raise MetaOAuthConfigurationError(f"Missing Meta OAuth setting(s): {', '.join(missing)}")

    return MetaOAuthConfig(
        app_id=app_id,
        app_secret=app_secret,
        graph_api_version=graph_api_version,
        redirect_uri=redirect_uri,
        scopes=scopes,
    )


def build_authorization_url(*, state: str) -> str:
    config = get_meta_oauth_config(require_secret=False)
    query = urlencode(
        {
            "client_id": config.app_id,
            "redirect_uri": config.redirect_uri,
            "state": state,
            "scope": config.scope_string,
            "response_type": "code",
        }
    )
    return f"https://www.facebook.com/{config.graph_api_version}/dialog/oauth?{query}"


def _graph_url(path: str, config: MetaOAuthConfig) -> str:
    normalized_path = path.lstrip("/")
    return f"https://graph.facebook.com/{config.graph_api_version}/{normalized_path}"


def _safe_response_json(response) -> dict[str, Any]:
    try:
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        raise MetaOAuthRequestError("Meta Graph request failed.") from exc

    if not isinstance(payload, dict):
        raise MetaOAuthRequestError("Meta Graph returned an invalid response.")

    if payload.get("error"):
        raise MetaOAuthRequestError("Meta Graph returned an error response.")

    return payload


def exchange_code_for_access_token(*, code: str) -> dict[str, Any]:
    config = get_meta_oauth_config(require_secret=True)
    response = requests.get(
        _graph_url("oauth/access_token", config),
        params={
            "client_id": config.app_id,
            "client_secret": config.app_secret,
            "redirect_uri": config.redirect_uri,
            "code": code,
        },
        timeout=10,
    )
    payload = _safe_response_json(response)

    if not payload.get("access_token"):
        raise MetaOAuthRequestError("Meta OAuth token response did not include an access token.")

    return payload


def fetch_meta_profile(*, access_token: str) -> dict[str, Any]:
    config = get_meta_oauth_config(require_secret=True)
    response = requests.get(
        _graph_url("me", config),
        params={"access_token": access_token, "fields": "id,name"},
        timeout=10,
    )
    return _safe_response_json(response)


def fetch_meta_accounts(*, access_token: str) -> dict[str, Any]:
    config = get_meta_oauth_config(require_secret=True)
    response = requests.get(
        _graph_url("me/accounts", config),
        params={
            "access_token": access_token,
            "fields": "id,name,access_token,instagram_business_account{id,username,name},perms,tasks",
        },
        timeout=10,
    )
    return _safe_response_json(response)


def _scrub_account(account: dict[str, Any]) -> dict[str, Any]:
    scrubbed = dict(account)
    scrubbed.pop("access_token", None)
    return scrubbed


def choose_connection_account(
    *,
    user_access_token: str,
    profile: dict[str, Any],
    accounts_payload: dict[str, Any],
) -> MetaOAuthAccount:
    accounts = accounts_payload.get("data")
    if isinstance(accounts, list) and accounts:
        first_account = accounts[0] if isinstance(accounts[0], dict) else {}
        external_account_id = str(first_account.get("id") or "").strip()
        if external_account_id:
            account_label = str(first_account.get("name") or external_account_id).strip()
            page_access_token = str(first_account.get("access_token") or user_access_token).strip()
            safe_accounts = [_scrub_account(account) for account in accounts if isinstance(account, dict)]
            return MetaOAuthAccount(
                external_account_id=external_account_id,
                account_label=account_label,
                access_token=page_access_token,
                metadata={
                    "meta_user": {
                        "id": profile.get("id"),
                        "name": profile.get("name"),
                    },
                    "selected_account": _scrub_account(first_account),
                    "accounts": safe_accounts,
                    "account_kind": "facebook_page",
                    "oauth_provider": "meta",
                    "no_external_post": True,
                },
            )

    profile_id = str(profile.get("id") or "").strip()
    if not profile_id:
        raise MetaOAuthRequestError("Meta profile response did not include an id.")

    return MetaOAuthAccount(
        external_account_id=profile_id,
        account_label=str(profile.get("name") or profile_id).strip(),
        access_token=user_access_token,
        metadata={
            "meta_user": {
                "id": profile.get("id"),
                "name": profile.get("name"),
            },
            "accounts": [],
            "account_kind": "meta_user",
            "oauth_provider": "meta",
            "no_external_post": True,
        },
    )


def expires_at_from_token_payload(token_payload: dict[str, Any]):
    expires_in = token_payload.get("expires_in")
    try:
        seconds = int(expires_in)
    except (TypeError, ValueError):
        return None

    if seconds <= 0:
        return None

    return timezone.now() + timedelta(seconds=seconds)
