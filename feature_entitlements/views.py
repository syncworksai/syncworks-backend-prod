from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError
from user_accounts.models import Business, BusinessMember
from .models import BusinessFeatureEntitlement, FEATURES
from .services import provider_budget_cents

def _is_founder(user):
    # Never trust an email string or frontend flag to confer God Mode rights.
    return bool(user.is_authenticated and (getattr(user, "is_platform_admin", False) or user.is_superuser))

def _owner_access(user, business):
    if business.owner_id == user.id: return True
    return BusinessMember.objects.filter(business=business, user=user, is_active=True, role__in=["OWNER", "MANAGER", "ADMIN"]).exists()

def _business(request, pk):
    obj = Business.objects.filter(pk=pk).first()
    if not obj: raise ValidationError("Business not found.")
    if not _owner_access(request.user, obj) and not _is_founder(request.user):
        raise PermissionDenied("Not authorized for this business.")
    return obj

def _payload(business):
    existing = {ent.feature: ent for ent in BusinessFeatureEntitlement.objects.filter(business=business)}
    result = []
    for feature in FEATURES:
        ent = existing.get(feature)
        result.append({"feature": feature,"state":ent.state if ent else "OFF","active":bool(ent and ent.active()),"trial_expires_at":ent.trial_expires_at if ent else None,"paid_through":ent.paid_through if ent else None,"override_expires_at":ent.override_expires_at if ent else None})
    return {"business_id": business.id,"features":result,"ai_provider_cost_ceiling_cents":provider_budget_cents()}

class BusinessFeaturesView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request, pk):
        return Response(_payload(_business(request, pk)))

class BusinessFeatureTrialView(APIView):
    permission_classes = [IsAuthenticated]
    @transaction.atomic
    def post(self, request, pk):
        business = _business(request, pk)
        feature = str(request.data.get("feature") or "").strip()
        if feature not in FEATURES: raise ValidationError({"feature":"Unknown feature."})
        row, _ = BusinessFeatureEntitlement.objects.select_for_update().get_or_create(business=business, feature=feature)
        if row.trial_started_at is not None:
            raise ValidationError("This business has already started a trial for this feature.")
        if row.state in ("PAID","OVERRIDE"): raise ValidationError("Feature already active.")
        row.state = "TRIAL"
        row.trial_started_at = timezone.now()
        row.trial_expires_at = row.trial_started_at + timedelta(days=30)
        row.modified_by = request.user
        row.save()
        return Response(_payload(business))

class FounderFeatureOverrideView(APIView):
    permission_classes = [IsAuthenticated]
    @transaction.atomic
    def post(self, request, pk):
        if not _is_founder(request.user): raise PermissionDenied("Founder access required.")
        business = _business(request, pk)
        feature = str(request.data.get("feature") or "").strip()
        state = str(request.data.get("state") or "").strip().upper()
        if feature not in FEATURES or state not in ("OVERRIDE","OFF"): raise ValidationError("Invalid feature or override state.")
        reason = str(request.data.get("reason") or "").strip()[:300]
        try: days = int(request.data.get("days", 30))
        except (ValueError,TypeError): raise ValidationError("Invalid expiry.")
        if state == "OVERRIDE" and (not reason or not 1 <= days <= 365): raise ValidationError("Override requires reason and 1-365 day expiration.")
        row, _ = BusinessFeatureEntitlement.objects.select_for_update().get_or_create(business=business, feature=feature)
        row.state = state
        row.override_reason = reason if state == "OVERRIDE" else ""
        row.override_expires_at = timezone.now() + timedelta(days=days) if state == "OVERRIDE" else None
        row.modified_by = request.user
        row.save()
        return Response(_payload(business))

class FounderStripePriceAuditView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        if not _is_founder(request.user):
            raise PermissionDenied("Founder access required.")
        from .pricing import inspect_stripe_prices
        return Response({"prices": inspect_stripe_prices(), "note": "Read-only price verification; does not activate or modify subscriptions."})
