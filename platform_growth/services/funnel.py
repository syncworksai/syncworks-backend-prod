from __future__ import annotations

from django.db.models import Count

from platform_growth.models import PlatformLead


def lead_status_breakdown() -> dict[str, int]:
    rows = PlatformLead.objects.values("status").annotate(total=Count("id"))
    return {row["status"]: int(row["total"]) for row in rows}
