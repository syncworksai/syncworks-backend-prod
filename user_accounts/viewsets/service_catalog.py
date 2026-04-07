from __future__ import annotations

from django.db.models import Q
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models import Business, BusinessMember, ServiceCatalogItem
from user_accounts.serializers.service_catalog import ServiceCatalogItemSerializer


def _get_active_business_from_request(request) -> Business | None:
    raw = (
        request.headers.get("X-Business-Id")
        or request.headers.get("x-business-id")
        or request.query_params.get("business_id")
        or ""
    )
    raw = str(raw).strip()
    if not raw:
        return None

    try:
        biz_id = int(raw)
    except Exception:
        return None

    biz = Business.objects.filter(id=biz_id, is_active=True).first()
    if not biz:
        return None

    u = request.user
    if getattr(u, "is_superuser", False) or getattr(u, "is_platform_admin", False):
        return biz

    if getattr(biz, "owner_id", None) == getattr(u, "id", None):
        return biz

    mem = BusinessMember.objects.filter(user_id=u.id, business_id=biz.id, is_active=True).first()
    if mem:
        return biz

    return None


def _can_manage_catalog(user, business: Business) -> bool:
    if getattr(user, "is_superuser", False) or getattr(user, "is_platform_admin", False):
        return True

    if getattr(business, "owner_id", None) == getattr(user, "id", None):
        return True

    mem = BusinessMember.objects.filter(
        user_id=user.id,
        business_id=business.id,
        is_active=True,
    ).first()
    if not mem:
        return False

    return bool(
        getattr(mem, "can_manage_categories", False)
        or getattr(mem, "can_manage_settings", False)
        or getattr(mem, "can_manage_invoices", False)
    )


class ServiceCatalogItemViewSet(viewsets.ModelViewSet):
    serializer_class = ServiceCatalogItemSerializer
    permission_classes = [IsAuthenticated]
    queryset = ServiceCatalogItem.objects.select_related("business").all().order_by("sort_order", "name", "id")

    def get_queryset(self):
        u = self.request.user
        qs = self.queryset

        if getattr(u, "is_superuser", False) or getattr(u, "is_platform_admin", False):
            biz = _get_active_business_from_request(self.request)
            if biz:
                qs = qs.filter(business_id=biz.id)
            else:
                biz_id = self.request.query_params.get("business_id")
                if biz_id:
                    try:
                        qs = qs.filter(business_id=int(biz_id))
                    except Exception:
                        return qs.none()
        else:
            biz = _get_active_business_from_request(self.request)
            if not biz:
                return qs.none()
            qs = qs.filter(business_id=biz.id)

        active_only = str(self.request.query_params.get("active_only") or "").strip().lower()
        if active_only in {"1", "true", "yes"}:
            qs = qs.filter(is_active=True)

        item_type = str(self.request.query_params.get("item_type") or "").strip().upper()
        if item_type:
            qs = qs.filter(item_type=item_type)

        featured = str(self.request.query_params.get("featured") or "").strip().lower()
        if featured in {"1", "true", "yes"}:
            qs = qs.filter(is_featured=True)

        q = str(self.request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(name__icontains=q) |
                Q(sku__icontains=q) |
                Q(description__icontains=q)
            )

        return qs.order_by("sort_order", "name", "id")

    def create(self, request, *args, **kwargs):
        biz = _get_active_business_from_request(request)
        if not biz:
            return Response({"detail": "X-Business-Id required."}, status=400)

        if not _can_manage_catalog(request.user, biz):
            return Response({"detail": "Not allowed."}, status=403)

        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        biz = _get_active_business_from_request(self.request)
        serializer.save(business=biz)

    def update(self, request, *args, **kwargs):
        obj = self.get_object()
        if not _can_manage_catalog(request.user, obj.business):
            return Response({"detail": "Not allowed."}, status=403)
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        obj = self.get_object()
        if not _can_manage_catalog(request.user, obj.business):
            return Response({"detail": "Not allowed."}, status=403)
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        if not _can_manage_catalog(request.user, obj.business):
            return Response({"detail": "Not allowed."}, status=403)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["post"], url_path="archive")
    def archive(self, request, pk=None):
        obj = self.get_object()
        if not _can_manage_catalog(request.user, obj.business):
            return Response({"detail": "Not allowed."}, status=403)

        obj.is_active = False
        obj.save(update_fields=["is_active", "updated_at"])
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"], url_path="activate")
    def activate(self, request, pk=None):
        obj = self.get_object()
        if not _can_manage_catalog(request.user, obj.business):
            return Response({"detail": "Not allowed."}, status=403)

        obj.is_active = True
        obj.save(update_fields=["is_active", "updated_at"])
        return Response(self.get_serializer(obj).data)