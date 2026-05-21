from __future__ import annotations

from urllib.parse import urlencode

from django.conf import settings

from platform_affiliates.constants import SYNCWORKS_BASE_REFERRAL_PATH


def build_referral_link(code: str) -> str:
    base_url = str(getattr(settings, "PLATFORM_BASE_URL", "http://localhost:5174")).rstrip("/")
    query = urlencode({"ref": code})
    return f"{base_url}{SYNCWORKS_BASE_REFERRAL_PATH}?{query}"


def build_qr_svg_placeholder(code: str) -> str:
    referral_link = build_referral_link(code)
    safe_code = str(code).replace("<", "").replace(">", "")
    safe_link = referral_link.replace("<", "").replace(">", "")

    return f"""
<svg xmlns="http://www.w3.org/2000/svg" width="360" height="360" viewBox="0 0 360 360">
  <rect width="360" height="360" rx="28" fill="#020617"/>
  <rect x="28" y="28" width="304" height="304" rx="24" fill="#0f172a" stroke="#22d3ee" stroke-width="3"/>
  <text x="180" y="142" text-anchor="middle" fill="#e2e8f0" font-size="22" font-family="Arial">SyncWorks Affiliate</text>
  <text x="180" y="184" text-anchor="middle" fill="#67e8f9" font-size="34" font-weight="700" font-family="Arial">{safe_code}</text>
  <text x="180" y="224" text-anchor="middle" fill="#cbd5e1" font-size="13" font-family="Arial">QR engine placeholder</text>
  <text x="180" y="250" text-anchor="middle" fill="#94a3b8" font-size="10" font-family="Arial">{safe_link}</text>
</svg>
""".strip()