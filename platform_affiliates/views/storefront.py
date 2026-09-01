from __future__ import annotations

import os
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from django.db.models import Count, Sum
from django.db.models.functions import Coalesce
from django.db.models import DecimalField, Value
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from platform_affiliates.permissions import IsGodModeAffiliateAdmin
from platform_affiliates.storefront_models import StorefrontClick, StorefrontEarning, StorefrontMerchant
from user_accounts.models import Business, BusinessMember


STORE_MODULES = {
    "PERSONAL_PROJECTS",
    "HEALTH",
    "BUSINESS",
    "PROPERTY_MANAGEMENT",
    "EVENTS",
    "DIRECT_STOREFRONT",
    "SYNC_RECOMMENDATION",
}


def _merchant_payload(merchant: StorefrontMerchant) -> dict:
    env_key = merchant.affiliate_tag_env_key.strip()
    return {
        "slug": merchant.slug,
        "name": merchant.name,
        "kind": merchant.kind,
        "status": merchant.status,
        "configured": bool(env_key and os.getenv(env_key)),
        "disclosure": merchant.disclosure,
    }


def _user_can_use_business(user, business: Business) -> bool:
    if business.owner_id == user.id:
        return True
    return BusinessMember.objects.filter(business=business, user=user, is_active=True).exists()


def _validated_host(url: str, merchant: StorefrontMerchant) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    host = parsed.hostname.lower().rstrip(".")
    allowed = [str(x).lower().rstrip(".") for x in (merchant.allowed_domains or []) if x]
    return any(host == domain or host.endswith(f".{domain}") for domain in allowed)


def _affiliate_url(url: str, merchant: StorefrontMerchant) -> str:
    if merchant.kind != "AMAZON":
        return url
    env_key = merchant.affiliate_tag_env_key.strip()
    tag = os.getenv(env_key, "").strip() if env_key else ""
    if not tag:
        return url
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["tag"] = tag
    return urlunparse(parsed._replace(query=urlencode(query)))


class StorefrontMerchantListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        merchants = StorefrontMerchant.objects.filter(status="ACTIVE").order_by("name")
        return Response({"merchants": [_merchant_payload(m) for m in merchants]})


class StorefrontTrackClickView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        merchant_slug = str(request.data.get("merchant") or "").strip().lower()
        module = str(request.data.get("module") or "DIRECT_STOREFRONT").strip().upper()
        destination_url = str(request.data.get("destination_url") or "").strip()

        if module not in STORE_MODULES:
            return Response({"detail": "Unsupported Storefront module."}, status=status.HTTP_400_BAD_REQUEST)
        if not merchant_slug or not destination_url:
            return Response({"detail": "merchant and destination_url are required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            merchant = StorefrontMerchant.objects.get(slug=merchant_slug, status="ACTIVE")
        except StorefrontMerchant.DoesNotExist:
            return Response({"detail": "Merchant is not active."}, status=status.HTTP_404_NOT_FOUND)

        if not _validated_host(destination_url, merchant):
            return Response({"detail": "Destination is not approved for this merchant."}, status=status.HTTP_400_BAD_REQUEST)

        if merchant.affiliate_tag_env_key and not os.getenv(merchant.affiliate_tag_env_key):
            return Response({"detail": "Merchant affiliate configuration is not ready."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        business = None
        business_id = request.data.get("business_id")
        if business_id:
            try:
                business = Business.objects.get(pk=business_id)
            except Business.DoesNotExist:
                return Response({"detail": "Business not found."}, status=status.HTTP_404_NOT_FOUND)
            if not _user_can_use_business(request.user, business):
                return Response({"detail": "Business access denied."}, status=status.HTTP_403_FORBIDDEN)

        outbound_url = _affiliate_url(destination_url, merchant)
        click = StorefrontClick.objects.create(
            merchant=merchant,
            user=request.user,
            business=business,
            module=module,
            need_reference=str(request.data.get("need_reference") or "")[:120],
            project_reference=str(request.data.get("project_reference") or "")[:120],
            product_reference=str(request.data.get("product_reference") or "")[:180],
            outbound_url=outbound_url,
            user_agent=str(request.META.get("HTTP_USER_AGENT") or "")[:2000],
        )
        return Response({"click_id": click.id, "outbound_url": outbound_url}, status=status.HTTP_201_CREATED)


class GodModeStorefrontKpiView(APIView):
    permission_classes = [IsGodModeAffiliateAdmin]

    def get(self, request):
        money_field = DecimalField(max_digits=12, decimal_places=2)
        earnings = StorefrontEarning.objects.exclude(status="REVERSED")
        total = earnings.aggregate(
            commission=Coalesce(Sum("commission_amount"), Value(0), output_field=money_field),
            gross_sales=Coalesce(Sum("gross_sales_amount"), Value(0), output_field=money_field),
        )
        by_module = {
            row["module"]: {
                "conversions": row["conversions"],
                "commission": str(row["commission"] or 0),
            }
            for row in earnings.values("module").annotate(
                conversions=Count("id"),
                commission=Coalesce(Sum("commission_amount"), Value(0), output_field=money_field),
            )
        }
        merchants = StorefrontMerchant.objects.order_by("name")
        return Response(
            {
                "affiliate_clicks": StorefrontClick.objects.count(),
                "reported_conversions": earnings.count(),
                "commission_earned": str(total["commission"] or 0),
                "gross_sales_referred": str(total["gross_sales"] or 0),
                "by_module": by_module,
                "merchants": [_merchant_payload(m) for m in merchants],
            }
        )
