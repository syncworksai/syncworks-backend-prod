from __future__ import annotations

from platform_affiliates.constants import DEFAULT_AFFILIATE_CODE_PREFIX
from platform_affiliates.models import AffiliatePartner


def normalize_affiliate_code(code: str) -> str:
    return (code or "").strip().upper().replace(" ", "")


def generate_affiliate_code(prefix: str = DEFAULT_AFFILIATE_CODE_PREFIX) -> str:
    normalized_prefix = normalize_affiliate_code(prefix) or DEFAULT_AFFILIATE_CODE_PREFIX

    existing_codes = set(
        AffiliatePartner.objects.filter(code__startswith=normalized_prefix)
        .values_list("code", flat=True)
    )

    for number in range(1, 10000):
        candidate = f"{normalized_prefix}{number:02d}"
        if candidate not in existing_codes:
            return candidate

    raise RuntimeError("Unable to generate affiliate code. Code space exhausted.")