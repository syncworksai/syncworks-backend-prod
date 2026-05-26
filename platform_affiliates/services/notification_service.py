from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from platform_affiliates.models import AffiliatePartner
from user_accounts.models import Business

logger = logging.getLogger(__name__)


def _business_display_name(business: Business) -> str:
    return (
        getattr(business, "name", "")
        or getattr(business, "business_name", "")
        or f"Business #{business.id}"
    )


def notify_affiliate_business_attributed(
    *,
    affiliate: AffiliatePartner,
    business: Business,
    referral_code: str,
) -> bool:
    recipient = (affiliate.email or affiliate.payout_email or "").strip()

    if not recipient:
        logger.info(
            "Affiliate attribution email skipped: affiliate_id=%s has no email.",
            affiliate.id,
        )
        return False

    business_name = _business_display_name(business)
    sent_at = timezone.localtime(timezone.now()).strftime("%b %d, %Y at %I:%M %p")

    subject = "New SyncWorks referral connected"

    body = (
        f"Good news — a new business was connected to your SyncWorks affiliate code.\n\n"
        f"Affiliate: {affiliate.name}\n"
        f"Affiliate Code: {referral_code}\n"
        f"Business: {business_name}\n"
        f"Connected: {sent_at}\n\n"
        f"You can view your referral activity, payout history, and business list inside your SyncWorks Affiliate Portal.\n\n"
        f"SyncWorks Team"
    )

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None)

    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=from_email,
            recipient_list=[recipient],
            fail_silently=False,
        )
        return True
    except Exception:
        logger.exception(
            "Failed sending affiliate attribution email: affiliate_id=%s business_id=%s",
            affiliate.id,
            business.id,
        )
        return False