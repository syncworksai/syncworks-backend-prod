from __future__ import annotations

from django.db import connection
from django.db.migrations.recorder import MigrationRecorder
from django.http import JsonResponse
from django.utils import timezone
from django.views import View


class LivenessView(View):
    """Cheap public probe used by the hosting layer to prove the app process is alive."""

    http_method_names = ["get", "head"]

    def get(self, request):
        return JsonResponse({
            "status": "ok",
            "service": "syncworks-backend",
            "probe": "liveness",
            "timestamp": timezone.now().isoformat(),
        })

    def head(self, request):
        return self.get(request)


class ReadinessView(View):
    """Public readiness probe. It exposes no secrets or customer data."""

    http_method_names = ["get", "head"]

    def get(self, request):
        database_ok = False
        migrations_ok = False
        detail = "ready"
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            database_ok = True
            # Reaching the migration table proves Django can query schema metadata.
            MigrationRecorder.Migration.objects.order_by("-applied").values_list("id", flat=True).first()
            migrations_ok = True
        except Exception:
            detail = "database_or_schema_unavailable"

        ready = database_ok and migrations_ok
        return JsonResponse(
            {
                "status": "ready" if ready else "not_ready",
                "service": "syncworks-backend",
                "probe": "readiness",
                "database": database_ok,
                "schema": migrations_ok,
                "detail": detail,
                "timestamp": timezone.now().isoformat(),
            },
            status=200 if ready else 503,
        )

    def head(self, request):
        return self.get(request)
