from __future__ import annotations

import os
import secrets

from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from sync_ai.billing_runtime import process_invoice_reminders
from sync_ai.github_oidc_billing import GitHubOIDCError, verify_billing_runtime_token


def _authorized_runtime_request(request) -> tuple[bool, str]:
    authorization = str(request.headers.get("Authorization") or "").strip()
    if authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        try:
            claims = verify_billing_runtime_token(token)
        except GitHubOIDCError:
            return False, "oidc"
        return True, f"github:{claims.get('run_id') or 'scheduled'}"

    expected = str(os.getenv("BILLING_RUNTIME_SECRET") or "").strip()
    supplied = str(
        request.headers.get("X-SyncWorks-Runtime-Secret")
        or request.headers.get("X-Billing-Runtime-Secret")
        or ""
    ).strip()
    if expected and supplied and secrets.compare_digest(supplied, expected):
        return True, "shared-secret"
    return False, "none"


class BillingRuntimeAPIView(APIView):
    """Authenticated scheduler entry point for invoice reminder automation."""

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        authorized, identity = _authorized_runtime_request(request)
        if not authorized:
            return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

        result = process_invoice_reminders(limit=1000)
        return Response(
            {
                "ok": True,
                "ran_at": timezone.now().isoformat(),
                "identity": identity,
                "invoice_reminders": result,
            }
        )
