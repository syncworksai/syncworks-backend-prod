from __future__ import annotations

from django.db.models import Q
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from user_accounts.models import ServiceCategory
from user_accounts.serializers.categories import ServiceCategorySerializer


def _truthy(v) -> bool:
    return str(v or "").strip().lower() in {"1", "true", "yes", "y", "on"}


class ServiceCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Wizard endpoints:
      GET /api/v1/service-categories/
      GET /api/v1/service-categories/roots/
      GET /api/v1/service-categories/{id}/children/
      GET /api/v1/service-categories/search/?q=jump
      GET /api/v1/service-categories/leaves/?parent=<id optional>
      GET /api/v1/service-categories/by-ids/?ids=1,2,3

    Optional query params on list:
      ?q=term
      ?parent=<id>
      ?roots=1
      ?leaf_only=1

    IMPORTANT:
    We disable pagination here because the setup wizard and category picker
    need the full active taxonomy, not just the first global DRF page.
    """
    serializer_class = ServiceCategorySerializer
    permission_classes = [AllowAny]
    pagination_class = None

    def _base_qs(self):
        return (
            ServiceCategory.objects
            .filter(is_active=True)
            .select_related("parent")
            .order_by("sort_order", "name")
        )

    def get_queryset(self):
        qs = self._base_qs()

        q = (self.request.query_params.get("q") or self.request.query_params.get("search") or "").strip()
        parent = self.request.query_params.get("parent")
        roots = _truthy(self.request.query_params.get("roots"))
        leaf_only = _truthy(self.request.query_params.get("leaf_only"))

        if roots:
            qs = qs.filter(parent__isnull=True)

        if parent not in (None, "", "null"):
            try:
                qs = qs.filter(parent_id=int(parent))
            except Exception:
                pass

        if q:
            parts = [p.strip() for p in q.split() if p.strip()]
            query = Q(name__icontains=q) | Q(key__icontains=q)
            for part in parts:
                query |= Q(name__icontains=part) | Q(key__icontains=part)
            qs = qs.filter(query).distinct()

        if leaf_only:
            ids = []
            for c in qs:
                if not c.children.filter(is_active=True).exists():
                    ids.append(c.id)
            qs = qs.filter(id__in=ids)

        return qs

    @action(detail=False, methods=["get"], url_path="roots")
    def roots(self, request):
        qs = self._base_qs().filter(parent__isnull=True)
        return Response(ServiceCategorySerializer(qs, many=True).data)

    @action(detail=True, methods=["get"], url_path="children")
    def children(self, request, pk=None):
        parent = self.get_object()
        qs = self._base_qs().filter(parent=parent)
        return Response(ServiceCategorySerializer(qs, many=True).data)

    @action(detail=False, methods=["get"], url_path="search")
    def search(self, request):
        q = (request.query_params.get("q") or "").strip()
        qs = self._base_qs()

        if q:
            parts = [p.strip() for p in q.split() if p.strip()]
            query = Q(name__icontains=q) | Q(key__icontains=q)
            for part in parts:
                query |= Q(name__icontains=part) | Q(key__icontains=part)
            qs = qs.filter(query).distinct()

        return Response(ServiceCategorySerializer(qs[:100], many=True).data)

    @action(detail=False, methods=["get"], url_path="by-ids")
    def by_ids(self, request):
        raw = (request.query_params.get("ids") or "").strip()
        if not raw:
            return Response([])

        ids = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                ids.append(int(part))
            except ValueError:
                continue

        if not ids:
            return Response([])

        qs = self._base_qs().filter(id__in=ids)
        by_id = {c.id: c for c in qs}
        ordered = [by_id[i] for i in ids if i in by_id]
        return Response(ServiceCategorySerializer(ordered, many=True).data)

    @action(detail=False, methods=["get"], url_path="leaves")
    def leaves(self, request):
        parent = request.query_params.get("parent")
        q = (request.query_params.get("q") or "").strip()

        qs = self._base_qs()

        if parent not in (None, "", "null"):
            try:
                qs = qs.filter(parent_id=int(parent))
            except Exception:
                pass

        if q:
            parts = [p.strip() for p in q.split() if p.strip()]
            query = Q(name__icontains=q) | Q(key__icontains=q)
            for part in parts:
                query |= Q(name__icontains=part) | Q(key__icontains=part)
            qs = qs.filter(query).distinct()

        leaf_ids = []
        for c in qs:
            if not c.children.filter(is_active=True).exists():
                leaf_ids.append(c.id)

        leaf_qs = qs.filter(id__in=leaf_ids)
        return Response(ServiceCategorySerializer(leaf_qs, many=True).data)

    @action(detail=False, methods=["get"], url_path="debug-count")
    def debug_count(self, request):
        return Response(
            {
                "total": ServiceCategory.objects.count(),
                "active_total": ServiceCategory.objects.filter(is_active=True).count(),
                "roots": ServiceCategory.objects.filter(is_active=True, parent__isnull=True).count(),
            }
        )