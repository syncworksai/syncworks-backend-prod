from __future__ import annotations


def build_outbound_payload(message_text: str) -> dict:
    return {
        "provider": "META",
        "message": message_text,
    }
