# backend/user_accounts/viewsets/subscriptions.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import stripe
from django.conf import settings
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models.business import Business, BusinessMember
from user_accounts.models.platform_billing import PlatformBillingProfile
from user_accounts.models.user_billing import UserBillingProfile


# ----------------------------
# Helpers
# ----------------------------
def _is_platform_admin(user) -> bool:
    return bool(getattr(user, "is_platform_admin", False) or getattr(user, "is_superuser", False))


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


def _get_membership(user, business_id: int) -> BusinessMember | None:
    return BusinessMember.objects.filter(business_id=business_id, user=user, is_active=True).first()


def _maybe_get_business_and_access(request):
    """
    Optional business resolver.
    Returns:
      (business, membership, err_response)
    If no business_id is supplied, this returns (None, None, None).
    """
    business_id = _get_business_id_from_request(request)
    if not business_id:
        return None, None, None

    business = Business.objects.filter(id=business_id).first()
    if not business:
        return None, None, Response({"detail": "Business not found."}, status=404)

    if _is_platform_admin(request.user) or business.owner_id == request.user.id:
        membership = _get_membership(request.user, business_id)
        return business, membership, None

    membership = _get_membership(request.user, business_id)
    if not membership:
        return None, None, Response({"detail": "You are not a member of this business."}, status=403)

    return business, membership, None


def _require_business_and_access(request):
    business, membership, err = _maybe_get_business_and_access(request)
    if err:
        return None, None, err
    if not business:
        return None, None, Response({"detail": "Business context missing (X-Business-Id)."}, status=400)
    return business, membership, None


def _sub_active(profile) -> bool:
    return (getattr(profile, "subscription_status", "") or "").lower() in ("active", "trialing")


# ----------------------------
# Stripe module config
# ----------------------------
@dataclass(frozen=True)
class ModuleDef:
    key: str
    label: str
    env_product: str
    env_price: str


MODULES: dict[str, ModuleDef] = {
    "SBO": ModuleDef("SBO", "SBO", "STRIPE_PRODUCT_ID_SBO", "STRIPE_PRICE_ID_SBO"),
    "PM": ModuleDef("PM", "PM", "STRIPE_PRODUCT_ID_PM", "STRIPE_PRICE_ID_PM"),
    "SALESOS": ModuleDef("SALESOS", "Sales OS", "STRIPE_PRODUCT_ID_SALESOS", "STRIPE_PRICE_ID_SALESOS"),
    "FINANCE": ModuleDef("FINANCE", "Finance", "STRIPE_PRODUCT_ID_FINANCE", "STRIPE_PRICE_ID_FINANCE"),
    "FITNESS": ModuleDef("FITNESS", "Fitness", "STRIPE_PRODUCT_ID_FITNESS", "STRIPE_PRICE_ID_FITNESS"),
}


def _norm_module_key(raw: str) -> str:
    s = (raw or "").strip().upper()
    if s in ("SALES", "SALES_OS", "SALES-OS", "SALES OS"):
        return "SALESOS"
    return s


def _stripe_price_for_product(product_id: str) -> str:
    """
    Checkout subscription requires a PRICE id, not a product id.
    This finds the first active monthly recurring price for the product.
    """
    prices = stripe.Price.list(product=product_id, active=True, limit=100)
    for p in prices.get("data", []):
        rec = p.get("recurring")
        if not rec:
            continue
        if rec.get("interval") != "month":
            continue
        if int(rec.get("interval_count") or 1) != 1:
            continue
        return str(p.get("id"))

    raise ValueError(f"No active monthly recurring price found for product {product_id}")


def _resolve_price_id_for_module(module_key: str) -> str:
    md = MODULES.get(module_key)
    if not md:
        raise ValueError(f"Unknown module: {module_key}")

    price_id = getattr(settings, md.env_price, "") or ""
    if price_id:
        return price_id

    product_id = getattr(settings, md.env_product, "") or ""
    if not product_id:
        raise ValueError(f"{md.env_product} not configured for module {module_key}")

    return _stripe_price_for_product(product_id)


def _setup_path_for_modules(modules: list[str]) -> str:
    """
    Decide where the frontend should send the user after successful checkout.
    """
    normalized = {_norm_module_key(m) for m in (modules or [])}

    if "SBO" in normalized:
        return "/upgrade/sbo"
    if "PM" in normalized:
        return "/upgrade/pm"
    if "SALESOS" in normalized:
        return "/upgrade/sales"
    return "/upgrade"


# ----------------------------
# APIs
# ----------------------------
class SubscriptionStatusAPIView(APIView):
    """
    Works in BOTH modes:

    1) User-first (no X-Business-Id):
       Returns the logged-in user's upgrade subscription status.

    2) Business-scoped (with X-Business-Id):
       Returns the linked business subscription status.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        business, membership, err = _maybe_get_business_and_access(request)
        if err:
            return err

        if business:
            profile, _ = PlatformBillingProfile.objects.get_or_create(business=business)
            return Response(
                {
                    "scope": "business",
                    "business_id": business.id,
                    "subscription_active": _sub_active(profile),
                    "subscription_status": profile.subscription_status or "none",
                    "cancel_at_period_end": bool(profile.subscription_cancel_at_period_end),
                    "current_period_end": profile.subscription_current_period_end,
                    "subscription_id": profile.stripe_subscription_id or "",
                }
            )

        user_profile, _ = UserBillingProfile.objects.get_or_create(user=request.user)
        return Response(
            {
                "scope": "user",
                "user_id": request.user.id,
                "subscription_active": _sub_active(user_profile),
                "subscription_status": user_profile.subscription_status or "none",
                "cancel_at_period_end": bool(getattr(user_profile, "subscription_cancel_at_period_end", False)),
                "current_period_end": getattr(user_profile, "subscription_current_period_end", None),
                "subscription_id": getattr(user_profile, "stripe_subscription_id", "") or "",
            }
        )


class CreateSubscriptionCheckoutSessionAPIView(APIView):
    """
    POST /billing/subscription/subscribe/

    CUSTOMER-FIRST FLOW:
    - No Business ID required.
    - Customer chooses modules.
    - Stripe checkout opens.
    - On success, return user to /upgrade with query params telling UI where setup should continue.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not getattr(settings, "STRIPE_SECRET_KEY", ""):
            return Response({"detail": "Stripe not configured (STRIPE_SECRET_KEY)."}, status=500)
        if not getattr(settings, "PLATFORM_BASE_URL", ""):
            return Response({"detail": "PLATFORM_BASE_URL not configured."}, status=500)

        stripe.api_key = settings.STRIPE_SECRET_KEY

        body: dict[str, Any] = request.data if isinstance(request.data, dict) else {}
        modules_in = body.get("modules") or []
        if isinstance(modules_in, str):
            modules_in = [modules_in]
        if not isinstance(modules_in, list):
            modules_in = []

        single = body.get("module")
        if single and not modules_in:
            modules_in = [single]

        if not modules_in:
            modules_in = ["SBO"]

        seen = set()
        modules: list[str] = []
        for m in modules_in:
            mk = _norm_module_key(str(m))
            if mk and mk not in seen:
                seen.add(mk)
                modules.append(mk)

        try:
            line_items = []
            for mk in modules:
                price_id = _resolve_price_id_for_module(mk)
                line_items.append({"price": price_id, "quantity": 1})
        except Exception as e:
            return Response({"detail": "Failed resolving Stripe prices.", "error": str(e)}, status=500)

        user_profile, _ = UserBillingProfile.objects.get_or_create(user=request.user)

        if not user_profile.stripe_customer_id:
            customer = stripe.Customer.create(
                email=getattr(request.user, "email", "") or "",
                name=f"User #{request.user.id}",
                metadata={"user_id": str(request.user.id)},
            )
            user_profile.stripe_customer_id = customer["id"]
            user_profile.save(update_fields=["stripe_customer_id"])

        next_setup_path = _setup_path_for_modules(modules)

        success_params = urlencode(
            {
                "sub": "success",
                "modules": ",".join(modules),
                "next": next_setup_path,
            }
        )
        cancel_params = urlencode(
            {
                "sub": "cancel",
                "modules": ",".join(modules),
            }
        )

        success_url = f"{settings.PLATFORM_BASE_URL}/upgrade?{success_params}"
        cancel_url = f"{settings.PLATFORM_BASE_URL}/upgrade?{cancel_params}"

        try:
            session = stripe.checkout.Session.create(
                mode="subscription",
                customer=user_profile.stripe_customer_id,
                line_items=line_items,
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    "user_id": str(request.user.id),
                    "modules": ",".join(modules),
                    "scope": "user",
                },
            )
            return Response(
                {
                    "url": session["url"],
                    "modules": modules,
                    "scope": "user",
                    "next": next_setup_path,
                }
            )
        except stripe.error.StripeError as e:
            return Response({"detail": "Stripe error creating subscription checkout.", "error": str(e)}, status=500)
        except Exception as e:
            return Response({"detail": "Unexpected error creating subscription checkout.", "error": str(e)}, status=500)


class CancelSubscriptionAPIView(APIView):
    """
    POST /billing/subscription/cancel/

    Supports:
    - user-first subscription cancel (no business header)
    - business-linked cancel (with business header)
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not getattr(settings, "STRIPE_SECRET_KEY", ""):
            return Response({"detail": "Stripe not configured (STRIPE_SECRET_KEY)."}, status=500)

        stripe.api_key = settings.STRIPE_SECRET_KEY

        business, membership, err = _maybe_get_business_and_access(request)
        if err:
            return err

        if business:
            profile, _ = PlatformBillingProfile.objects.get_or_create(business=business)

            if not profile.stripe_subscription_id:
                return Response({"detail": "No subscription found for this business."}, status=400)

            try:
                sub = stripe.Subscription.modify(profile.stripe_subscription_id, cancel_at_period_end=True)
                profile.subscription_cancel_at_period_end = bool(sub.get("cancel_at_period_end"))
                profile.subscription_status = sub.get("status") or profile.subscription_status
                cpe = sub.get("current_period_end")
                if cpe:
                    profile.subscription_current_period_end = timezone.datetime.fromtimestamp(int(cpe), tz=timezone.utc)
                profile.save(
                    update_fields=[
                        "subscription_cancel_at_period_end",
                        "subscription_status",
                        "subscription_current_period_end",
                    ]
                )
                return Response(
                    {
                        "scope": "business",
                        "detail": "Subscription will cancel at period end (no refunds).",
                        "cancel_at_period_end": profile.subscription_cancel_at_period_end,
                        "current_period_end": profile.subscription_current_period_end,
                        "subscription_status": profile.subscription_status,
                    }
                )
            except stripe.error.StripeError as e:
                return Response({"detail": "Stripe error canceling subscription.", "error": str(e)}, status=500)
            except Exception as e:
                return Response({"detail": "Unexpected error canceling subscription.", "error": str(e)}, status=500)

        user_profile, _ = UserBillingProfile.objects.get_or_create(user=request.user)

        if not getattr(user_profile, "stripe_subscription_id", ""):
            return Response({"detail": "No subscription found for this user."}, status=400)

        try:
            sub = stripe.Subscription.modify(user_profile.stripe_subscription_id, cancel_at_period_end=True)
            user_profile.subscription_cancel_at_period_end = bool(sub.get("cancel_at_period_end"))
            user_profile.subscription_status = sub.get("status") or user_profile.subscription_status
            cpe = sub.get("current_period_end")
            if cpe:
                user_profile.subscription_current_period_end = timezone.datetime.fromtimestamp(int(cpe), tz=timezone.utc)
            user_profile.save(
                update_fields=[
                    "subscription_cancel_at_period_end",
                    "subscription_status",
                    "subscription_current_period_end",
                ]
            )
            return Response(
                {
                    "scope": "user",
                    "detail": "Subscription will cancel at period end (no refunds).",
                    "cancel_at_period_end": user_profile.subscription_cancel_at_period_end,
                    "current_period_end": user_profile.subscription_current_period_end,
                    "subscription_status": user_profile.subscription_status,
                }
            )
        except stripe.error.StripeError as e:
            return Response({"detail": "Stripe error canceling subscription.", "error": str(e)}, status=500)
        except Exception as e:
            return Response({"detail": "Unexpected error canceling subscription.", "error": str(e)}, status=500)