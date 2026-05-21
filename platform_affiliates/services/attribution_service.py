from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from platform_affiliates.choices import AttributionSource
from platform_affiliates.models import AffiliateAuditLog, AffiliatePartner, ReferralAttribution
from user_accounts.models import Business


def get_client_ip(request) -> str | None:
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


def snapshot_attribution(attribution: ReferralAttribution | None) -> dict[str, Any]:
    if not attribution:
        return {}

    return {
        "id": attribution.id,
        "business_id": attribution.business_id,
        "affiliate_id": attribution.affiliate_id,
        "referral_code": attribution.referral_code,
        "attribution_source": attribution.attribution_source,
        "effective_from": attribution.effective_from.isoformat() if attribution.effective_from else None,
        "retroactive": attribution.retroactive,
    }


@transaction.atomic
def assign_business_to_affiliate(
    *,
    business: Business,
    affiliate: AffiliatePartner,
    actor,
    source: str = AttributionSource.GODMODE_MANUAL,
    reason: str = "",
    effective_from=None,
    retroactive: bool = False,
) -> ReferralAttribution:
    if ReferralAttribution.objects.filter(business=business).exists():
        raise ValidationError({"business_id": "This business already has an affiliate attribution."})

    attribution = ReferralAttribution.objects.create(
        business=business,
        affiliate=affiliate,
        referral_code=affiliate.code,
        attribution_source=source,
        assigned_by=actor if getattr(actor, "is_authenticated", False) else None,
        admin_note=reason or "",
        effective_from=effective_from or timezone.localdate(),
        retroactive=bool(retroactive),
    )

    AffiliateAuditLog.objects.create(
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        affiliate=affiliate,
        business=business,
        action="AFFILIATE_BUSINESS_ASSIGNED",
        before_json={},
        after_json=snapshot_attribution(attribution),
        note=reason or "",
    )

    return attribution