from __future__ import annotations

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import Business, BusinessVerification


CHECK_FIELDS = {
    "email_verified",
    "phone_verified",
    "identity_verified",
    "business_details_verified",
    "payment_verified",
    "license_verified",
    "insurance_verified",
    "background_verified",
}


def _is_platform_admin(user) -> bool:
    return bool(getattr(user, "is_platform_admin", False) or getattr(user, "is_superuser", False))


def _payload(business, verification):
    checks = verification.public_checks()
    return {
        "business": {
            "id": business.id,
            "name": business.name,
            "business_email": business.business_email,
            "phone": business.phone,
            "owner_id": business.owner_id,
            "city": business.city,
            "state": business.state,
            "website": business.website,
            "logo_url": business.logo.url if business.logo else None,
        },
        "status": verification.status,
        "checks": checks,
        "verified_count": sum(1 for value in checks.values() if value),
        "total_checks": len(checks),
        "review_notes": verification.review_notes,
        "submitted_at": verification.submitted_at.isoformat() if verification.submitted_at else None,
        "verified_at": verification.verified_at.isoformat() if verification.verified_at else None,
        "updated_at": verification.updated_at.isoformat() if verification.updated_at else None,
        "disclaimer": "Verification confirms only the checks shown. It is not a guarantee or endorsement of service quality.",
    }


class PlatformBusinessVerificationQueueAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _is_platform_admin(request.user):
            return Response({"detail": "Platform administrator access is required."}, status=status.HTTP_403_FORBIDDEN)

        status_filter = str(request.query_params.get("status") or "IN_REVIEW").upper()
        rows = BusinessVerification.objects.select_related("business").filter(business__is_active=True)
        allowed = {choice[0] for choice in BusinessVerification.Status.choices}
        if status_filter != "ALL" and status_filter in allowed:
            rows = rows.filter(status=status_filter)
        rows = rows.order_by("-submitted_at", "-updated_at")[:250]
        payload = [_payload(row.business, row) for row in rows]
        counts = {
            key: BusinessVerification.objects.filter(status=key, business__is_active=True).count()
            for key in allowed
        }
        return Response({"results": payload, "counts": counts, "status": status_filter})


class PlatformBusinessTrustAPIView(APIView):
    """God Mode review endpoint. Verification is never granted by self-report."""

    permission_classes = [IsAuthenticated]

    def _resolve(self, request, business_id):
        if not _is_platform_admin(request.user):
            return None, None, Response(
                {"detail": "Platform administrator access is required."},
                status=status.HTTP_403_FORBIDDEN,
            )
        business = Business.objects.filter(id=business_id, is_active=True).first()
        if not business:
            return None, None, Response({"detail": "Business not found."}, status=status.HTTP_404_NOT_FOUND)
        verification, _ = BusinessVerification.objects.get_or_create(business=business)
        return business, verification, None

    def get(self, request, business_id):
        business, verification, error = self._resolve(request, business_id)
        if error:
            return error
        return Response(_payload(business, verification))

    def patch(self, request, business_id):
        business, verification, error = self._resolve(request, business_id)
        if error:
            return error

        update_fields = []
        for field in CHECK_FIELDS:
            if field in request.data:
                value = request.data.get(field)
                if isinstance(value, str):
                    value = value.strip().lower() in {"1", "true", "yes", "on"}
                setattr(verification, field, bool(value))
                update_fields.append(field)

        if "review_notes" in request.data:
            verification.review_notes = str(request.data.get("review_notes") or "")[:5000]
            update_fields.append("review_notes")

        requested_status = str(request.data.get("status") or "").upper()
        allowed = {choice[0] for choice in BusinessVerification.Status.choices}
        if requested_status in allowed:
            verification.status = requested_status
            update_fields.append("status")
            if requested_status == BusinessVerification.Status.VERIFIED:
                verification.verified_at = timezone.now()
                update_fields.append("verified_at")
            elif requested_status != BusinessVerification.Status.VERIFIED and verification.verified_at:
                verification.verified_at = None
                update_fields.append("verified_at")

        if update_fields:
            verification.save(update_fields=list(dict.fromkeys([*update_fields, "updated_at"])))
        return Response(_payload(business, verification))
