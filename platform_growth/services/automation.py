from __future__ import annotations

from django.utils import timezone

from platform_growth.models import PlatformAutomationFlow


def mark_flow_run(flow: PlatformAutomationFlow) -> PlatformAutomationFlow:
    flow.last_run_at = timezone.now()
    flow.save(update_fields=["last_run_at", "updated_at"])
    return flow
