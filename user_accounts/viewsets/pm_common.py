from __future__ import annotations

from rest_framework.exceptions import PermissionDenied, ValidationError

from user_accounts.models.business import Business, BusinessMember


def get_business_from_header(request) -> Business:
    raw = request.headers.get("X-Business-Id") or request.META.get("HTTP_X_BUSINESS_ID")
    if not raw:
        raise ValidationError({"detail": "Missing X-Business-Id header."})
    try:
        bid = int(raw)
    except Exception:
        raise ValidationError({"detail": "Invalid X-Business-Id header."})

    try:
        return Business.objects.get(id=bid)
    except Business.DoesNotExist:
        raise ValidationError({"detail": "Business not found."})


def require_business_access(user, business: Business) -> None:
    if business.owner_id == user.id:
        return
    if BusinessMember.objects.filter(business=business, user=user, is_active=True).exists():
        return
    raise PermissionDenied("You do not have access to this business.")
