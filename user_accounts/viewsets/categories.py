# user_accounts/viewsets/categories.py
from __future__ import annotations

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from user_accounts.models import ServiceCategory
from user_accounts.serializers.categories import ServiceCategorySerializer


class ServiceCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Wizard endpoints:
      GET /api/v1/service-categories/roots/
      GET /api/v1/service-categories/{id}/children/
      GET /api/v1/service-categories/search/?q=jump
      GET /api/v1/service-categories/leaves/?parent=<id optional>
      GET /api/v1/service-categories/by-ids/?ids=1,2,3
    """
    serializer_class = ServiceCategorySerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return (
            ServiceCategory.objects
            .filter(is_active=True)
            .order_by("sort_order", "name")
        )

    @action(detail=False, methods=["get"], url_path="roots")
    def roots(self, request):
        qs = self.get_queryset().filter(parent__isnull=True)
        return Response(ServiceCategorySerializer(qs, many=True).data)

    @action(detail=True, methods=["get"], url_path="children")
    def children(self, request, pk=None):
        parent = self.get_object()
        qs = self.get_queryset().filter(parent=parent)
        return Response(ServiceCategorySerializer(qs, many=True).data)

    @action(detail=False, methods=["get"], url_path="search")
    def search(self, request):
        q = (request.query_params.get("q") or "").strip()
        qs = self.get_queryset()
        if q:
            qs = qs.filter(name__icontains=q)
        return Response(ServiceCategorySerializer(qs[:50], many=True).data)

    @action(detail=False, methods=["get"], url_path="by-ids")
    def by_ids(self, request):
        """
        Fetch categories by comma-separated IDs (for rendering selected leaf labels).
        Example: /api/v1/service-categories/by-ids/?ids=12,13,14
        """
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

        qs = self.get_queryset().filter(id__in=ids)
        # preserve original order
        by_id = {c.id: c for c in qs}
        ordered = [by_id[i] for i in ids if i in by_id]
        return Response(ServiceCategorySerializer(ordered, many=True).data)

    @action(detail=False, methods=["get"], url_path="leaves")
    def leaves(self, request):
        parent = request.query_params.get("parent")
        qs = self.get_queryset()

        if parent:
            qs = qs.filter(parent_id=parent)

        # leaf = no active children
        leaf_ids = [
            c.id for c in qs
            if not c.children.filter(is_active=True).exists()
        ]
        leaves = self.get_queryset().filter(id__in=leaf_ids)
        return Response(ServiceCategorySerializer(leaves, many=True).data)
