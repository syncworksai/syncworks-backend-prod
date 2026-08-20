from __future__ import annotations

from user_accounts.models.user_classification import PlatformUserClassification
from user_accounts.viewsets.auth import RegisterAPIView


_original_register_post = RegisterAPIView.post

KNOWN_SOURCES = {
    "DIRECT", "FACEBOOK", "INSTAGRAM", "LINKEDIN", "TIKTOK", "YOUTUBE", "X", "GOOGLE",
    "REFERRAL", "AFFILIATE", "BUSINESS_INVITE", "PM_INVITE", "TENANT_INVITE", "OTHER", "UNKNOWN",
}


def _clean(value):
    return str(value or "").strip()


def _source_from_request(request):
    data = request.data if isinstance(request.data, dict) else {}
    affiliate = _clean(data.get("affiliate_code") or data.get("affiliateCode"))
    if affiliate:
        return "AFFILIATE", f"affiliate_code={affiliate}"

    explicit = _clean(data.get("acquisition_source") or data.get("utm_source") or data.get("source")).upper()
    normalized = {
        "META": "FACEBOOK",
        "FB": "FACEBOOK",
        "FACEBOOK": "FACEBOOK",
        "IG": "INSTAGRAM",
        "INSTAGRAM": "INSTAGRAM",
        "GOOGLE": "GOOGLE",
        "LINKEDIN": "LINKEDIN",
        "TIKTOK": "TIKTOK",
        "YOUTUBE": "YOUTUBE",
        "X": "X",
        "TWITTER": "X",
        "REFERRAL": "REFERRAL",
        "AFFILIATE": "AFFILIATE",
        "BUSINESS_INVITE": "BUSINESS_INVITE",
        "PM_INVITE": "PM_INVITE",
        "TENANT_INVITE": "TENANT_INVITE",
        "DIRECT": "DIRECT",
        "WEB": "DIRECT",
    }.get(explicit, explicit if explicit in KNOWN_SOURCES else "")

    registration_source = _clean(data.get("registration_source") or data.get("registrationSource")).upper()
    if not normalized:
        normalized = {
            "WEB": "DIRECT",
            "DIRECT": "DIRECT",
            "BUSINESS_INVITE": "BUSINESS_INVITE",
            "PM_INVITE": "PM_INVITE",
            "TENANT_INVITE": "TENANT_INVITE",
            "REFERRAL": "REFERRAL",
        }.get(registration_source, "UNKNOWN")

    details = []
    for key in ("utm_source", "utm_medium", "utm_campaign", "utm_content", "referral_code", "promo_code", "registration_source"):
        value = _clean(data.get(key))
        if value:
            details.append(f"{key}={value}")
    return normalized or "UNKNOWN", "; ".join(details)


def _post(self, request, *args, **kwargs):
    response = _original_register_post(self, request, *args, **kwargs)
    if getattr(response, "status_code", 500) >= 400:
        return response

    try:
        user_payload = response.data.get("user") if isinstance(response.data, dict) else None
        user_id = user_payload.get("id") if isinstance(user_payload, dict) else None
        if user_id:
            from django.contrib.auth import get_user_model
            user = get_user_model().objects.filter(id=user_id).first()
            if user is not None:
                item, _ = PlatformUserClassification.objects.get_or_create(user=user)
                intelligence = dict(item.intelligence or {})
                current_source = str(intelligence.get("acquisition_source") or "UNKNOWN").upper()
                if current_source in {"", "UNKNOWN"}:
                    source, detail = _source_from_request(request)
                    intelligence["acquisition_source"] = source
                    if detail:
                        intelligence["acquisition_detail"] = detail
                    item.intelligence = intelligence
                    item.save(update_fields=["intelligence", "updated_at"])
    except Exception:
        # Registration must never fail because attribution capture failed.
        pass
    return response


RegisterAPIView.post = _post
