from __future__ import annotations

from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpResponseRedirect
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response

from platform_growth.models import GrowthChannelConnection, GrowthOAuthState
from platform_growth.services.oauth_state import is_state_expired
from platform_growth.views import OAuthMetaCallbackAPIView, OAuthMetaStartAPIView


_ALLOWED_RETURN_PATHS = {"/sbo/growth", "/sbo/settings"}


def _safe_return_path(value: object) -> str:
    path = str(value or "").strip()
    return path if path in _ALLOWED_RETURN_PATHS else ""


def _frontend_url(path: str, *, params: dict[str, str] | None = None) -> str:
    base = str(getattr(settings, "FRONTEND_BASE_URL", "") or "https://syncworksapp.com").rstrip("/")
    suffix = path if path.startswith("/") else f"/{path}"
    query = urlencode(params or {})
    return f"{base}{suffix}{'?' + query if query else ''}"


class EasyOAuthMetaStartAPIView(OAuthMetaStartAPIView):
    """Start Meta OAuth and remember an allow-listed in-app return path."""

    def post(self, request):
        response = super().post(request)
        if response.status_code >= 400:
            return response

        return_to = _safe_return_path(request.data.get("return_to"))
        state_token = str(response.data.get("state") or "").strip()
        if return_to and state_token:
            state_obj = GrowthOAuthState.objects.filter(state=state_token).first()
            if state_obj is not None:
                metadata = dict(state_obj.metadata or {})
                metadata["return_to"] = return_to
                state_obj.metadata = metadata
                state_obj.save(update_fields=["metadata", "updated_at"])
        return response


class EasyOAuthMetaCallbackAPIView(OAuthMetaCallbackAPIView):
    """Complete OAuth using the one-time state as callback authentication.

    Meta redirects directly to this endpoint and cannot attach the SyncWorks API
    token. We therefore validate the high-entropy, pending, unexpired OAuth state,
    bind the request to that state's owner, and then reuse the existing callback
    implementation. The existing callback consumes the state so it cannot be
    replayed.
    """

    authentication_classes = []
    permission_classes = []

    def get(self, request):
        state_token = str(request.query_params.get("state") or "").strip()
        state_obj = GrowthOAuthState.objects.select_related("created_by").filter(
            state=state_token,
            provider=GrowthChannelConnection.Provider.META,
        ).first()

        if state_obj is None:
            return Response({"detail": "Invalid OAuth state."}, status=status.HTTP_400_BAD_REQUEST)
        if state_obj.status != GrowthOAuthState.Status.PENDING:
            return Response({"detail": "OAuth state is not pending."}, status=status.HTTP_400_BAD_REQUEST)
        if is_state_expired(state_obj.expires_at):
            state_obj.status = GrowthOAuthState.Status.EXPIRED
            state_obj.save(update_fields=["status", "updated_at"])
            return Response({"detail": "OAuth state has expired."}, status=status.HTTP_400_BAD_REQUEST)
        if state_obj.created_by is None:
            return Response({"detail": "OAuth state owner is missing."}, status=status.HTTP_400_BAD_REQUEST)

        request.user = state_obj.created_by
        response = super().get(request)

        return_to = _safe_return_path((state_obj.metadata or {}).get("return_to"))
        if not return_to:
            return response

        if response.status_code >= 400:
            return HttpResponseRedirect(
                _frontend_url(return_to, params={"social_error": str(response.data.get("detail") or "connection_failed")})
            )

        connection = response.data.get("connection") or {}
        provider = str(response.data.get("requested_channel") or connection.get("provider") or "meta").lower()
        label = str(connection.get("account_label") or "").strip()
        return HttpResponseRedirect(
            _frontend_url(
                return_to,
                params={
                    "social_connected": provider,
                    "social_label": label,
                },
            )
        )
