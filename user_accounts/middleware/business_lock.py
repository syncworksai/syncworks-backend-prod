# backend/user_accounts/middleware/business_lock.py
from __future__ import annotations

from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin

from user_accounts.services.god_mode import is_god_mode

# Prefer PlatformBillingProfile as source of truth for lock state.
try:
    from user_accounts.models.platform_billing import PlatformBillingProfile  # type: ignore
except Exception:  # pragma: no cover
    PlatformBillingProfile = None  # type: ignore

# Back-compat: some older builds used BusinessAccessControl. Keep as fallback.
try:
    from user_accounts.models.business_access import BusinessAccessControl  # type: ignore
except Exception:  # pragma: no cover
    BusinessAccessControl = None  # type: ignore


class BusinessLockMiddleware(MiddlewareMixin):
    """
    If X-Business-Id is present and that business is locked, block requests
    EXCEPT allowlisted endpoints (billing + unlock request + auth + platform admin).

    IMPORTANT BUSINESS RULES:
      - While locked (CASH_FEE_OVERDUE), the business must STILL be able to:
          * View Cash Fee invoices so they can pay
          * View Marketplace queue (read-only)
      - But they should NOT be able to take ticket actions / create invoices / etc.
    """

    # Broad allowlist (always allowed regardless of method)
    ALLOWLIST_PREFIXES = (
        "/api/v1/auth",
        "/api/v1/billing",
        "/api/v1/stripe",        # webhook path (if you use it)
        "/api/v1/connect",       # allow Connect onboarding / status
        "/api/v1/platform",      # ✅ God Mode must ALWAYS be reachable
        "/api/v1/support",       # ✅ keep support reachable while locked
        "/api/v1/me",            # optional: allow reading own profile
         # ✅ allow viewing while locked (so they can pay + still see work)
        "/api/v1/cash-fee-invoices",
        "/api/v1/tickets/marketplace",
        "/admin",                # optional: Django admin recovery
        "/media",                # optional: don't block media
        "/static",               # optional: don't block static
    )

    # Method-limited allowlist (ONLY safe read methods while locked)
    # Keep these exact (do NOT open all /tickets/).
    ALLOWLIST_READONLY_PREFIXES = (
        "/api/v1/cash-fee-invoices",
        "/api/v1/tickets/marketplace",
    )

    SAFE_METHODS = ("GET", "HEAD", "OPTIONS")

    @staticmethod
    def _norm_path(p: str) -> str:
        # Normalize trailing slashes so /x and /x/ behave the same.
        # Keep leading slash intact.
        p = (p or "").strip()
        if p != "/" and p.endswith("/"):
            p = p.rstrip("/")
        return p

    def process_request(self, request):
        biz_id = request.headers.get("X-Business-Id") or request.META.get("HTTP_X_BUSINESS_ID")
        if not biz_id:
            return None

        raw_path = request.path or ""
        path = self._norm_path(raw_path)
        method = (request.method or "GET").upper()

        # Always-allowed prefixes
        for prefix in self.ALLOWLIST_PREFIXES:
            if path.startswith(self._norm_path(prefix)):
                return None

        # Read-only allowlist (GET/HEAD/OPTIONS only)
        if method in self.SAFE_METHODS:
            for prefix in self.ALLOWLIST_READONLY_PREFIXES:
                if path.startswith(self._norm_path(prefix)):
                    return None

        user = getattr(request, "user", None)

        # ✅ God Mode / platform admin bypass (never block)
        if user and getattr(user, "is_authenticated", False):
            if (
                getattr(user, "is_platform_admin", False)
                or getattr(user, "is_superuser", False)
                or is_god_mode(user)
            ):
                return None

        try:
            biz_id_int = int(str(biz_id).strip())
        except Exception:
            return JsonResponse({"detail": "Invalid X-Business-Id header."}, status=400)

        # ✅ Source of truth: PlatformBillingProfile.is_locked
        if PlatformBillingProfile is not None:
            try:
                prof = PlatformBillingProfile.objects.filter(business_id=biz_id_int).first()
                if prof and bool(getattr(prof, "is_locked", False)):
                    return JsonResponse(
                        {
                            "detail": "Business account is locked. Update billing or submit an unlock request.",
                            "lock_reason": getattr(prof, "lock_reason", "") or "",
                            "business_id": biz_id_int,
                        },
                        status=423,
                    )
                return None
            except Exception:
                pass

        # ✅ Legacy fallback (only if present)
        if BusinessAccessControl is not None:
            try:
                bac = BusinessAccessControl.objects.filter(business_id=biz_id_int).first()
                if not bac or not getattr(bac, "is_locked", False):
                    return None
                return JsonResponse(
                    {
                        "detail": "Business account is locked. Update billing or submit an unlock request.",
                        "lock_reason": getattr(bac, "lock_reason", "") or "",
                        "business_id": biz_id_int,
                    },
                    status=423,
                )
            except Exception:
                return None

        return None