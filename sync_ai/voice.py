from __future__ import annotations

import os
from dataclasses import dataclass

import requests


DEFAULT_ELEVENLABS_VOICE_ID = "kSiaSqSOAHNl8g8caZB5"
DEFAULT_ELEVENLABS_MODEL = "eleven_multilingual_v2"
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"


class SyncVoiceConfigurationError(RuntimeError):
    pass


class SyncVoiceProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class SyncVoiceAudio:
    content: bytes
    content_type: str
    voice_id: str
    model_id: str
    request_id: str
    character_cost: str


VOICE_CONTEXTS = {
    "default": "ELEVENLABS_SYNC_VOICE_ID",
    "forge": "ELEVENLABS_FORGE_VOICE_ID",
    "assistant": "ELEVENLABS_GEMMA_VOICE_ID",
    "health": "ELEVENLABS_HEALTH_VOICE_ID",
}


def configured_context_voice_id(context: str) -> str:
    """Select a server-configured voice. Never accept arbitrary provider voice IDs."""
    if context not in VOICE_CONTEXTS:
        raise ValueError("Unsupported voice context.")
    env_name = VOICE_CONTEXTS[context]
    explicit = (os.getenv(env_name) or "").strip()
    if explicit:
        return explicit
    if context != "default":
        raise SyncVoiceConfigurationError(f"{context} voice has not been configured.")
    return configured_voice_id()


def configured_voice_id() -> str:
    return (
        os.getenv("ELEVENLABS_SYNC_VOICE_ID")
        or DEFAULT_ELEVENLABS_VOICE_ID
    ).strip()


def configured_model_id() -> str:
    return (
        os.getenv("ELEVENLABS_SYNC_MODEL")
        or DEFAULT_ELEVENLABS_MODEL
    ).strip()


def elevenlabs_configured() -> bool:
    return bool((os.getenv("ELEVENLABS_API_KEY") or "").strip())


def synthesize_sync_voice(text: str, context: str = "default") -> SyncVoiceAudio:
    api_key = (os.getenv("ELEVENLABS_API_KEY") or "").strip()
    if not api_key:
        raise SyncVoiceConfigurationError("ELEVENLABS_API_KEY is not configured.")

    voice_id = configured_context_voice_id(context)
    model_id = configured_model_id()
    output_format = (
        os.getenv("ELEVENLABS_SYNC_OUTPUT_FORMAT")
        or DEFAULT_OUTPUT_FORMAT
    ).strip()

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    try:
        response = requests.post(
            url,
            params={"output_format": output_format},
            headers={
                "xi-api-key": api_key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            json={
                "text": text,
                "model_id": model_id,
                "voice_settings": {
                    "stability": 0.55,
                    "similarity_boost": 0.78,
                    "style": 0.18,
                    "use_speaker_boost": True,
                },
            },
            timeout=75,
        )
    except requests.RequestException as exc:
        raise SyncVoiceProviderError("ElevenLabs could not be reached.") from exc

    if response.status_code >= 400:
        detail = ""
        try:
            payload = response.json()
            detail = str(payload.get("detail") or payload.get("message") or "")
        except Exception:
            detail = response.text[:240]
        raise SyncVoiceProviderError(
            f"ElevenLabs returned {response.status_code}: {detail[:240]}"
        )

    if not response.content:
        raise SyncVoiceProviderError("ElevenLabs returned empty audio.")

    return SyncVoiceAudio(
        content=response.content,
        content_type=response.headers.get("content-type") or "audio/mpeg",
        voice_id=voice_id,
        model_id=model_id,
        request_id=response.headers.get("request-id") or "",
        character_cost=response.headers.get("character-cost") or "",
    )
