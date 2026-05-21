from __future__ import annotations

from django.utils import timezone

from platform_affiliates.constants import DEFAULT_AGREEMENT_VERSION
from platform_affiliates.models import (
    AffiliateAgreementAcceptance,
    AffiliateAgreementTemplate,
    AffiliatePartner,
)


DEFAULT_AFFILIATE_AGREEMENT_BODY = """
SYNCWORKS AFFILIATE AGREEMENT

By applying to the SyncWorks Affiliate Program, you agree that:

1. You are applying as an independent affiliate and not as an employee of SyncWorks.
2. Affiliate commissions are calculated only from actual net SyncWorks revenue collected from businesses attributed to your referral code.
3. SyncWorks may pay 10% of net SyncWorks collected revenue connected to your referred businesses, including eligible platform fees, subscriptions, Growth OS fees, and approved future SyncWorks revenue streams.
4. Commissions are not calculated from gross business revenue. They are calculated only from SyncWorks revenue actually collected.
5. Payouts may be reviewed, adjusted, delayed, voided, or clawed back for refunds, fraud, chargebacks, billing errors, duplicate attribution, or policy violations.
6. One business may only have one affiliate attribution.
7. SyncWorks may manually assign a business to an affiliate in God Mode when appropriate and audit all manual assignment activity.
8. You agree not to misrepresent SyncWorks, spam potential users, impersonate SyncWorks staff, or make unauthorized claims.
9. You agree to keep confidential any non-public SyncWorks information, business information, payout data, internal metrics, or platform operations shared with you.
10. SyncWorks may suspend or deactivate affiliate accounts at its discretion for fraud, abuse, misrepresentation, inactivity, or policy violations.
11. This agreement does not create a partnership, employment relationship, franchise, joint venture, or ownership interest.
12. SyncWorks may update this agreement over time. Future participation may require accepting a newer version.

By checking the agreement box and submitting your application, you acknowledge that you have read and accepted this agreement.
""".strip()


def get_or_create_active_agreement_template() -> AffiliateAgreementTemplate:
    active = AffiliateAgreementTemplate.objects.filter(is_active=True).order_by("-created_at").first()

    if active:
        return active

    return AffiliateAgreementTemplate.objects.create(
        version=DEFAULT_AGREEMENT_VERSION,
        title="SyncWorks Affiliate Agreement",
        body=DEFAULT_AFFILIATE_AGREEMENT_BODY,
        is_active=True,
    )


def record_agreement_acceptance(
    *,
    affiliate: AffiliatePartner,
    user,
    ip_address: str | None,
    user_agent: str = "",
) -> AffiliateAgreementAcceptance:
    template = get_or_create_active_agreement_template()
    accepted_at = affiliate.agreement_accepted_at or timezone.now()

    affiliate.agreement_version = template.version
    affiliate.agreement_accepted_at = accepted_at
    affiliate.agreement_accepted_ip = ip_address
    affiliate.agreement_accepted_user_agent = user_agent or ""
    affiliate.save(
        update_fields=[
            "agreement_version",
            "agreement_accepted_at",
            "agreement_accepted_ip",
            "agreement_accepted_user_agent",
            "updated_at",
        ]
    )

    return AffiliateAgreementAcceptance.objects.create(
        affiliate=affiliate,
        user=user if getattr(user, "is_authenticated", False) else None,
        agreement_version=template.version,
        agreement_title=template.title,
        agreement_body_snapshot=template.body,
        accepted_at=accepted_at,
        ip_address=ip_address,
        user_agent=user_agent or "",
    )