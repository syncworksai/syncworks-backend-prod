from __future__ import annotations

import os
import secrets

from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from platform_growth.services.runtime import (
    prepare_due_scheduled_posts,
    publish_ready_scheduled_posts,
    run_due_recipes,
)


class GrowthRuntimeAPIView(APIView):
    """Secret-protected scheduler entry point for unattended Growth automation."""

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        expected = str(os.getenv("GROWTH_RUNTIME_SECRET") or "").strip()
        supplied = str(
            request.headers.get("X-SyncWorks-Runtime-Secret")
            or request.headers.get("X-Growth-Runtime-Secret")
            or ""
        ).strip()

        if not expected:
            return Response(
                {"detail": "Growth runtime is not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if not supplied or not secrets.compare_digest(supplied, expected):
            return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

        now = timezone.now()
        recipe_results = run_due_recipes(limit=100, now=now)
        prepared = prepare_due_scheduled_posts(limit=50, now=now)
        published = publish_ready_scheduled_posts(limit=25, now=now)

        recipe_counts = {"completed": 0, "failed": 0, "skipped": 0}
        for _, result in recipe_results:
            key = str(result.status or "").lower()
            if key in recipe_counts:
                recipe_counts[key] += 1

        return Response(
            {
                "ok": True,
                "ran_at": now.isoformat(),
                "recipes": {"due": len(recipe_results), **recipe_counts},
                "scheduled_posts": prepared,
                "publishing": published,
            }
        )
