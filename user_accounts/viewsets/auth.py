from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework import status

from user_accounts.serializers.auth import RegisterSerializer, TokenLoginSerializer
from user_accounts.serializers.users import UserMeSerializer
from user_accounts.models.business import Business, BusinessMember
from user_accounts.models import PlatformBillingProfile
from user_accounts.models.promo import PromoCode, PromoRedemption
from user_accounts.models.user_billing import UserBillingProfile

User = get_user_model()


def _is_platform_admin(user) -> bool:
    return bool(getattr(user, "is_platform_admin", False) or getattr(user, "is_superuser", False))


def _business_id_from_request(request) -> int | None:
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


def _promo_upgrade_enabled() -> bool:
    return str(getattr(settings, "SW_PROMO_UPGRADE_ENABLED", True)).lower() in ("1", "true", "yes", "y", "on")


def _legacy_promo_code() -> str:
    return str(getattr(settings, "SW_PROMO_UPGRADE_CODE", "SWFF26") or "SWFF26").strip()


def _is_billing_exempt_now(business: Business) -> bool:
    if not getattr(business, "billing_exempt", False):
        return False
    until = getattr(business, "billing_exempt_until", None)
    if not until:
        return True
    return until >= timezone.localdate()


def _is_subscriptions_exempt_now(business: Business) -> bool:
    if not getattr(business, "subscriptions_exempt", False):
        return False
    until = getattr(business, "subscriptions_exempt_until", None)
    if not until:
        return True
    return until >= timezone.localdate()


def _subscription_active(profile: PlatformBillingProfile | None) -> bool:
    if not profile:
        return False
    return (profile.subscription_status or "").lower() in ("active", "trialing")


def _ensure_owner_membership_and_upgrade_user(user, business: Business) -> BusinessMember | None:
    membership = BusinessMember.objects.filter(business=business, user=user, is_active=True).first()
    is_owner = business.owner_id == user.id

    if is_owner and not membership:
        membership = BusinessMember.objects.create(
            business=business,
            user=user,
            role=BusinessMember.ROLE_OWNER,
            is_active=True,
        )
        if hasattr(membership, "apply_role_defaults"):
            membership.apply_role_defaults()
            membership.save()

    if is_owner and membership and membership.role != BusinessMember.ROLE_OWNER:
        membership.role = BusinessMember.ROLE_OWNER
        if hasattr(membership, "apply_role_defaults"):
            membership.apply_role_defaults()
        membership.save()

    if getattr(user, "role", "CUSTOMER") != "SBO":
        user.role = "SBO"
        user.save(update_fields=["role"])

    return membership


def _get_or_create_user_billing_profile(user) -> UserBillingProfile:
    prof, _ = UserBillingProfile.objects.get_or_create(user=user)
    return prof


def _grant_user_private_access(
    *,
    user,
    code: str,
    billing_exempt: bool,
    subscriptions_waived: bool,
) -> UserBillingProfile:
    prof = _get_or_create_user_billing_profile(user)
    prof.grant_beta_access(
        code=code,
        billing_exempt=billing_exempt,
        subscriptions_waived=subscriptions_waived,
    )
    prof.save(
        update_fields=[
            "beta_access_granted",
            "beta_access_granted_at",
            "beta_access_code",
            "beta_billing_exempt",
            "beta_subscriptions_waived",
        ]
    )

    if getattr(user, "role", "CUSTOMER") != "SBO":
        user.role = "SBO"
        user.save(update_fields=["role"])

    return prof


def _apply_private_access_to_business(
    *,
    business: Business,
    user,
    code: str,
    billing_exempt: bool,
    subscriptions_waived: bool,
    promo: PromoCode | None = None,
) -> None:
    changed = []

    if billing_exempt and not getattr(business, "billing_exempt", False):
        business.billing_exempt = True
        business.billing_exempt_reason = "Private access code"
        business.billing_exempt_until = None
        changed.extend(["billing_exempt", "billing_exempt_reason", "billing_exempt_until"])

    if subscriptions_waived and not getattr(business, "subscriptions_exempt", False):
        business.subscriptions_exempt = True
        business.subscriptions_exempt_reason = "Private access code"
        business.subscriptions_exempt_until = None
        changed.extend(["subscriptions_exempt", "subscriptions_exempt_reason", "subscriptions_exempt_until"])

    if changed:
        business.save(update_fields=changed)

    if promo:
        already = PromoRedemption.objects.filter(promo=promo, business=business).exists()
        if not already:
            PromoRedemption.objects.create(promo=promo, user=user, business=business)
            promo.redemption_count = (promo.redemption_count or 0) + 1
            promo.save(update_fields=["redemption_count"])


class RegisterAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = RegisterSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        return Response(
            {"token": result["token"], "user": UserMeSerializer(result["user"]).data},
            status=status.HTTP_201_CREATED,
        )


class TokenLoginAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = TokenLoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        return Response(serializer.validated_data, status=status.HTTP_200_OK)


class MeAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        return Response(UserMeSerializer(request.user).data, status=status.HTTP_200_OK)


class LogoutAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        if request.auth:
            try:
                request.auth.delete()
            except Exception:
                pass
        return Response({"detail": "Logged out"}, status=status.HTTP_200_OK)


class UpgradeToSboAPIView(APIView):
    """
    POST /auth/upgrade-to-sbo/
    Requires:
      - business context header or business_id
      - user has access to business
      - AND either:
          (billing_exempt) OR (subscriptions_exempt) OR (subscription active) OR platform admin
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        business_id = _business_id_from_request(request)
        if not business_id:
            return Response(
                {"detail": "Business context missing. Select a business first (X-Business-Id or business_id)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        business = Business.objects.filter(id=business_id).first()
        if not business:
            return Response({"detail": "Business not found."}, status=status.HTTP_404_NOT_FOUND)

        membership = BusinessMember.objects.filter(business=business, user=request.user, is_active=True).first()
        is_owner = business.owner_id == request.user.id

        if not (_is_platform_admin(request.user) or is_owner or membership):
            return Response({"detail": "You do not have access to this business."}, status=status.HTTP_403_FORBIDDEN)

        if not _is_platform_admin(request.user):
            profile = PlatformBillingProfile.objects.filter(business=business).first()
            if not (_is_billing_exempt_now(business) or _is_subscriptions_exempt_now(business) or _subscription_active(profile)):
                return Response(
                    {"detail": "Subscription required (or promo). Please subscribe first."},
                    status=status.HTTP_402_PAYMENT_REQUIRED,
                )

        membership = _ensure_owner_membership_and_upgrade_user(request.user, business)

        return Response(
            {
                "detail": "Upgraded to SBO.",
                "business_id": business.id,
                "role": getattr(membership, "role", None),
                "user": UserMeSerializer(request.user).data,
            },
            status=status.HTTP_200_OK,
        )


class UpgradeToSboPromoAPIView(APIView):
    """
    POST /auth/upgrade-to-sbo-promo/
    Body: { "code": "XXXX" }

    ✅ NEW FLOW:
      - If business_id exists -> apply immediately to that business
      - If business_id missing -> grant user-level SBO/private access first
      - First business created later will inherit the waiver
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        if not _promo_upgrade_enabled():
            return Response({"detail": "Promo upgrade is disabled."}, status=status.HTTP_403_FORBIDDEN)

        code = str((request.data or {}).get("code", "")).strip()
        if not code:
            return Response({"detail": "Promo code is required."}, status=status.HTTP_400_BAD_REQUEST)

        # 1) Resolve promo rule
        promo = PromoCode.objects.filter(code__iexact=code).first()
        billing_exempt = False
        subscriptions_waived = False

        if promo:
            if not promo.is_valid_now():
                return Response({"detail": "Promo code is expired or inactive."}, status=status.HTTP_400_BAD_REQUEST)
            billing_exempt = bool(getattr(promo, "billing_exempt", False))
            subscriptions_waived = bool(getattr(promo, "waive_subscriptions", False))
        else:
            if code != _legacy_promo_code():
                return Response({"detail": "Invalid promo code."}, status=status.HTTP_400_BAD_REQUEST)
            billing_exempt = False
            subscriptions_waived = True

        # 2) Always unlock user-level SBO access first
        _grant_user_private_access(
            user=request.user,
            code=code,
            billing_exempt=billing_exempt,
            subscriptions_waived=subscriptions_waived,
        )

        # 3) If no business yet, stop here successfully
        business_id = _business_id_from_request(request)
        if not business_id:
            return Response(
                {
                    "detail": "Private access code applied ✅ You can now create your business.",
                    "needs_business_setup": True,
                    "billing_exempt": billing_exempt,
                    "subscriptions_exempt": subscriptions_waived,
                    "user": UserMeSerializer(request.user).data,
                },
                status=status.HTTP_200_OK,
            )

        # 4) If business exists, apply immediately to that business too
        business = Business.objects.filter(id=business_id).first()
        if not business:
            return Response({"detail": "Business not found."}, status=status.HTTP_404_NOT_FOUND)

        membership = BusinessMember.objects.filter(business=business, user=request.user, is_active=True).first()
        is_owner = business.owner_id == request.user.id

        if not (_is_platform_admin(request.user) or is_owner or membership):
            return Response({"detail": "You do not have access to this business."}, status=status.HTTP_403_FORBIDDEN)

        _apply_private_access_to_business(
            business=business,
            user=request.user,
            code=code,
            billing_exempt=billing_exempt,
            subscriptions_waived=subscriptions_waived,
            promo=promo,
        )

        membership = _ensure_owner_membership_and_upgrade_user(request.user, business)

        return Response(
            {
                "detail": "Private access code applied — SBO unlocked ✅",
                "business_id": business.id,
                "billing_exempt": _is_billing_exempt_now(business),
                "subscriptions_exempt": _is_subscriptions_exempt_now(business),
                "role": getattr(membership, "role", None),
                "user": UserMeSerializer(request.user).data,
            },
            status=status.HTTP_200_OK,
        )