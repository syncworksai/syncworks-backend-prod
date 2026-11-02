"""Coarse pre-provider abuse gate; not a replacement for provider moderation or system rules."""
import re

_DISALLOWED = (
    re.compile(r"\b(?:generate|write|describe|show|create)\b.{0,100}\b(?:porn|explicit sexual|erotic|sexual roleplay|nsfw)\b", re.I | re.S),
    re.compile(r"\b(?:bypass|disable|ignore)\b.{0,70}\b(?:safety|moderation|content filter)\b", re.I | re.S),
)

def business_prompt_allowed(message: str) -> bool:
    text = str(message or "").strip()
    if not text or len(text) > 6000:
        return False
    return not any(pattern.search(text) for pattern in _DISALLOWED)
