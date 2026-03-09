# backend/user_accounts/viewsets/pm_documents.py
from __future__ import annotations

from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.exceptions import PermissionDenied

from user_accounts.models import BusinessMember
from user_accounts.models.pm_document import PMDocument
from user_accounts.serializers.pm_documents import PMDocumentSerializer


def _get_active_business_id(request) -> int:
    raw = request.headers.get("X-Business-Id") or request.META.get("HTTP_X_BUSINESS_ID") or ""
    raw = str(raw).strip()
    if not raw.isdigit():
        raise ValueError("Missing or invalid X-Business-Id header.")
    return int(raw)


class PMDocumentViewSet(viewsets.ModelViewSet):
    serializer_class = PMDocumentSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def _require_member(self, biz_id: int) -> None:
        if not BusinessMember.objects.filter(user=self.request.user, business_id=biz_id).exists():
            raise PermissionDenied("Not a member of this business.")

    def get_queryset(self):
        biz_id = _get_active_business_id(self.request)
        self._require_member(biz_id)

        return (
            PMDocument.objects.filter(business_id=biz_id)
            .select_related("property", "unit", "tenant")
            .order_by("-updated_at", "-id")
        )

    def perform_create(self, serializer):
        biz_id = _get_active_business_id(self.request)
        self._require_member(biz_id)
        serializer.save(business_id=biz_id, uploaded_by=self.request.user)
