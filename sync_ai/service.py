from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any

import requests
from django.conf import settings

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


class SyncAIConfigurationError(RuntimeError):
    pass


class SyncAIProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class SyncAIResult:
    text: str
    model: str
    response_id: str
    input_tokens: int
    output_tokens: int
    total_tokens: int


def ai_enabled() -> bool:
    raw = os.getenv("OPENAI_AI_ENABLED", "true")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def configured_model() -> str:
    return (
        os.getenv("OPENAI_SYNC_MODEL")
        or os.getenv("OPENAI_MODEL")
        or "gpt-5-mini"
    ).strip()


def _api_key() -> str:
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        raise SyncAIConfigurationError("OPENAI_API_KEY is not configured.")
    return key


def safety_identifier(user_id: Any) -> str:
    secret = str(settings.SECRET_KEY)
    raw = f"syncworks:{user_id}:{secret}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:64]


def _extract_text(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    parts: list[str] = []
    for item in payload.get("output") or []:
        for content in item.get("content") or []:
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    return "\n".join(parts).strip()


def create_sync_response(
    *,
    user_id: Any,
    message: str,
    instructions: str,
    metadata: dict[str, str],
    timeout_seconds: int = 45,
) -> SyncAIResult:
    if not ai_enabled():
        raise SyncAIConfigurationError("SYNC AI is currently disabled.")

    model = configured_model()
    body = {
        "model": model,
        "instructions": instructions,
        "input": message,
        "store": False,
        "safety_identifier": safety_identifier(user_id),
        "metadata": {str(k): str(v)[:512] for k, v in metadata.items()},
    }

    try:
        response = requests.post(
            OPENAI_RESPONSES_URL,
            headers={
                "Authorization": f"Bearer {_api_key()}",
                "Content-Type": "application/json",
            },
            data=json.dumps(body),
            timeout=timeout_seconds,
        )
    except requests.RequestException as exc:
        raise SyncAIProviderError("SYNC could not reach its AI provider.") from exc

    if response.status_code >= 400:
        try:
            detail = response.json().get("error", {}).get("message", "")
        except ValueError:
            detail = ""
        safe_detail = detail[:240] if detail else f"HTTP {response.status_code}"
        raise SyncAIProviderError(f"AI provider rejected the request: {safe_detail}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise SyncAIProviderError("AI provider returned an invalid response.") from exc

    text = _extract_text(payload)
    if not text:
        raise SyncAIProviderError("SYNC did not receive a usable response.")

    usage = payload.get("usage") or {}
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or input_tokens + output_tokens)

    return SyncAIResult(
        text=text,
        model=str(payload.get("model") or model),
        response_id=str(payload.get("id") or ""),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )
