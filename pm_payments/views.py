"""PM payment collection onboarding only.

Never create bank accounts or move rent. Stripe's hosted onboarding owns sensitive
bank information. External providers are recorded but not remotely called.
"""
from urllib.parse import urlsplit
import ipaddress
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models.stripe_connect import StripeConnectProfile
from user_accounts.viewsets.stripe_connect import _require_business_and_access
from .models import PMCollectionSetup


def _external_url(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if len(value) > 500:
        raise ValidationError({"external_provider_url": "URL too long."})
    parsed = urlsplit(value)
    if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValidationError({"external_provider_url": "Provide a secure HTTPS provider URL."})
    try:
        port = parsed.port
    except ValueError:
        raise ValidationError({"external_provider_url": "Invalid provider URL port."})
    if port and port != 443:
        raise ValidationError({"external_provider_url": "Non-standard ports are not supported."})
    try:
        ipaddress.ip_address(parsed.hostname)
        raise ValidationError({"external_provider_url": "IP addresses are not accepted as provider URLs."})
    except ValueError:
        pass
    if parsed.hostname.lower() in ("localhost",) or "." not in parsed.hostname:
        raise ValidationError({"external_provider_url": "Use a public HTTPS domain."})
    return value


def setup_status(business, setup):
    stripe_profile = StripeConnectProfile.objects.filter(business=business).first()
    connected = bool(business.stripe_connect_account_id)
    charges = bool(stripe_profile and stripe_profile.charges_enabled)
    payouts = bool(stripe_profile and stripe_profile.payouts_enabled)
    reasons = []
    if setup.method == PMCollectionSetup.Method.UNCONFIGURED:
        reasons.append("Select a payment collection method.")
    if setup.method == PMCollectionSetup.Method.STRIPE_CONNECT and not (connected and charges and payouts):
        reasons.append("Complete and verify the connected merchant bank account.")
    if setup.method == PMCollectionSetup.Method.EXTERNAL:
        reasons.append("Existing provider is not yet integrated. Record bank-verified receipts manually.")
    if setup.method == PMCollectionSetup.Method.MANUAL:
        reasons.append("Cash/check receipts must be verified and recorded manually.")
    if setup.method == PMCollectionSetup.Method.STRIPE_CONNECT and not setup.trust_account_reviewed_at:
        reasons.append("Business must review lawful rent collection/trust account arrangements.")
    # This is a hard stop while the PM checkout, trust accounting and webhook
    # are audited. Never equate Stripe onboarding with permission to collect rent.
    reasons.append("Online rent checkout and $1 fee are not yet enabled or independently reconciled.")
    return {
        "business_id": business.id,
        "method": setup.method,
        "external_provider_name": setup.external_provider_name,
        "external_provider_url": setup.external_provider_url,
        "trust_account_reviewed": bool(setup.trust_account_reviewed_at),
        "trust_account_reviewed_at": setup.trust_account_reviewed_at,
        "connected": connected,
        "charges_enabled": charges,
        "payouts_enabled": payouts,
        "stripe_status_checked_at": stripe_profile.last_checked_at if stripe_profile else None,
        "online_rent_collection_enabled": False,
        "fee_policy": {"amount_cents": 100, "basis": "successful_eligible_online_payment",
                       "live": False, "processing_cost": "not_finalized"},
        "readiness_reasons": reasons,
        "updated_at": setup.updated_at,
    }


class PMCollectionSetupAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        business, _membership, error = _require_business_and_access(request)
        if error:
            return error
        setup, _ = PMCollectionSetup.objects.get_or_create(business_id=business.id)
        return Response(setup_status(business, setup))

    def patch(self, request):
        business, _membership, error = _require_business_and_access(request)
        if error:
            return error
        incoming = request.data or {}
        allowed = {"method", "external_provider_name", "external_provider_url", "trust_account_reviewed"}
        if set(incoming) - allowed:
            raise ValidationError({"detail": "Unsupported payment setup fields."})
        setup, _ = PMCollectionSetup.objects.get_or_create(business_id=business.id)
        method = str(incoming.get("method", setup.method)).upper()
        if method not in PMCollectionSetup.Method.values:
            raise ValidationError({"method": "Choose Stripe Connect, existing processor, or cash/check."})
        provider_name = str(incoming.get("external_provider_name", setup.external_provider_name)).strip()
        if len(provider_name) > 100:
            raise ValidationError({"external_provider_name": "Maximum 100 characters."})
        provider_url = _external_url(str(incoming.get("external_provider_url", setup.external_provider_url)))
        if method == PMCollectionSetup.Method.EXTERNAL and not provider_name:
            raise ValidationError({"external_provider_name": "Name your existing processor."})
        setup.method = method
        setup.external_provider_name = provider_name if method == PMCollectionSetup.Method.EXTERNAL else ""
        setup.external_provider_url = provider_url if method == PMCollectionSetup.Method.EXTERNAL else ""
        if incoming.get("trust_account_reviewed") is True and not setup.trust_account_reviewed_at:
            setup.trust_account_reviewed_at = timezone.now()
            setup.trust_account_reviewed_by_id = request.user.id
        # A false or missing checkbox does not erase a previously logged attestation.
        # Attestation is NOT regulatory approval or a live-rent payment authorization.
        setup.updated_by_id = request.user.id
        setup.save()
        return Response(setup_status(business, setup))
