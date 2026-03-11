from __future__ import annotations

import stripe
from django.conf import settings
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models.business import Business, BusinessMember
from user_accounts.models.stripe_connect import StripeConnectProfile


def _stripe_key() -> str:
    return getattr(settings, "STRIPE_SECRET_KEY", "") or ""


def _platform_base_url() -> str:
    return (getattr(settings, "PLATFORM_BASE_URL", "") or "").rstrip("/") or "http://localhost:5174"


def _is_platform_admin(user) -> bool:
    return bool(
        getattr(user, "is_platform_admin", False)
        or getattr(user, "is_superuser", False)
        or getattr(user, "is_staff", False)
    )


def _get_business_id_from_request(request) -> int | None:
    raw = (
        request.headers.get("X-Business-Id")
        or request.headers.get("X-Business-ID")
        or request.headers.get("x-business-id")
        or request.query_params.get("business_id")
        or (request.data.get("business_id") if isinstance(request.data, dict) else None)
    )
    if not raw:
        return None
    try:
        return int(str(raw).strip())
    except Exception:
        return None


def _require_business_and_access(request):
    biz_id = _get_business_id_from_request(request)
    if not biz_id:
        return None, None, Response(
            {"detail": "Business context missing. Provide X-Business-Id header or ?business_id=."},
            status=400,
        )

    biz = Business.objects.filter(id=biz_id, is_active=True).first()
    if not biz:
        return None, None, Response({"detail": "Business not found."}, status=404)

    if _is_platform_admin(request.user):
        return biz, None, None

    if biz.owner_id == request.user.id:
        mem = BusinessMember.objects.filter(
            business_id=biz.id, user=request.user, is_active=True
        ).first()
        return biz, mem, None

    mem = BusinessMember.objects.filter(
        business_id=biz.id, user=request.user, is_active=True
    ).first()
    if not mem:
        return None, None, Response({"detail": "You are not a member of this business."}, status=403)

    if not getattr(mem, "can_manage_settings", False) and not getattr(mem, "is_owner", False):
        return None, None, Response({"detail": "Not allowed."}, status=403)

    return biz, mem, None


def _get_or_create_profile(business: Business) -> StripeConnectProfile:
    prof, _ = StripeConnectProfile.objects.get_or_create(business=business)
    return prof


def _sync_profile_from_account(profile: StripeConnectProfile, acct: dict) -> None:
    charges_enabled = bool(acct.get("charges_enabled"))
    payouts_enabled = bool(acct.get("payouts_enabled"))
    details_submitted = bool(acct.get("details_submitted"))

    req = acct.get("requirements") or {}
    currently_due = req.get("currently_due") or []
    eventually_due = req.get("eventually_due") or []
    past_due = req.get("past_due") or []
    pending = req.get("pending_verification") or []

    onboarding_completed = bool(charges_enabled and payouts_enabled)

    profile.charges_enabled = charges_enabled
    profile.payouts_enabled = payouts_enabled
    profile.details_submitted = details_submitted
    profile.onboarding_completed = onboarding_completed
    profile.requirements_due = {
        "currently_due": currently_due,
        "eventually_due": eventually_due,
        "past_due": past_due,
        "pending_verification": pending,
    }
    profile.last_checked_at = timezone.now()
    profile.save(
        update_fields=[
            "charges_enabled",
            "payouts_enabled",
            "details_submitted",
            "onboarding_completed",
            "requirements_due",
            "last_checked_at",
            "updated_at",
        ]
    )


class StripeConnectExpressStartAPIView(APIView):
    """
    POST /connect/express/start/
    Creates (or reuses) a Stripe Connect Express account for this Business
    and returns an onboarding link URL.

    Requires business context: X-Business-Id header (or ?business_id=).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not _stripe_key():
            return Response(
                {"detail": "Stripe is not configured (missing STRIPE_SECRET_KEY)."},
                status=500,
            )

        business, membership, err = _require_business_and_access(request)
        if err:
            return err

        stripe.api_key = _stripe_key()

        if not business.stripe_connect_account_id:
            acct = stripe.Account.create(
                type="express",
                country="US",
                capabilities={
                    "card_payments": {"requested": True},
                    "transfers": {"requested": True},
                },
                business_profile={
                    "name": business.name,
                    "support_email": business.business_email or None,
                },
                metadata={"business_id": str(business.id)},
            )
            business.stripe_connect_account_id = acct["id"]
            business.save(update_fields=["stripe_connect_account_id"])

            prof = _get_or_create_profile(business)
            _sync_profile_from_account(prof, acct)
        else:
            prof = _get_or_create_profile(business)

        base = _platform_base_url()

        # ✅ Route users back into the real SettingsHub route
        refresh_url = f"{base}/settings?connect=refresh&return=/sbo"
        return_url = f"{base}/settings?connect=return&return=/sbo"

        link = stripe.AccountLink.create(
            account=business.stripe_connect_account_id,
            type="account_onboarding",
            refresh_url=refresh_url,
            return_url=return_url,
        )

        return Response(
            {
                "business_id": business.id,
                "stripe_connect_account_id": business.stripe_connect_account_id,
                "url": link["url"],
            }
        )


class StripeConnectExpressStatusAPIView(APIView):
    """
    GET /connect/express/status/
    Returns Stripe Connect status for this Business and updates local snapshot.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _stripe_key():
            return Response(
                {"detail": "Stripe is not configured (missing STRIPE_SECRET_KEY)."},
                status=500,
            )

        business, membership, err = _require_business_and_access(request)
        if err:
            return err

        if not business.stripe_connect_account_id:
            return Response(
                {
                    "business_id": business.id,
                    "connected": False,
                    "stripe_connect_account_id": "",
                    "charges_enabled": False,
                    "payouts_enabled": False,
                    "onboarding_completed": False,
                    "requirements_due": {},
                }
            )

        stripe.api_key = _stripe_key()
        acct = stripe.Account.retrieve(business.stripe_connect_account_id)

        prof = _get_or_create_profile(business)
        _sync_profile_from_account(prof, acct)

        return Response(
            {
                "business_id": business.id,
                "connected": True,
                "stripe_connect_account_id": business.stripe_connect_account_id,
                "charges_enabled": prof.charges_enabled,
                "payouts_enabled": prof.payouts_enabled,
                "onboarding_completed": prof.onboarding_completed,
                "details_submitted": prof.details_submitted,
                "requirements_due": prof.requirements_due,
                "last_checked_at": prof.last_checked_at,
            }
        )