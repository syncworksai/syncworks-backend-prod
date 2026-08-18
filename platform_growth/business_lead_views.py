from __future__ import annotations

from platform_growth.models import PlatformConversation, PlatformLead
from platform_growth.views import PlatformConversationViewSet as BasePlatformConversationViewSet
from platform_growth.views import PlatformLeadViewSet as BasePlatformLeadViewSet
from user_accounts.services.god_mode import is_god_mode


class PlatformLeadViewSet(BasePlatformLeadViewSet):
    def get_queryset(self):
        qs = PlatformLead.objects.all().order_by("-last_activity_at", "-created_at")
        if is_god_mode(self.request.user):
            return qs
        if (getattr(self.request.user, "role", "") or "").upper() != "SBO":
            return qs.none()
        return qs.filter(assigned_to=self.request.user)

    def perform_create(self, serializer):
        if is_god_mode(self.request.user):
            return super().perform_create(serializer)
        lead = serializer.save(assigned_to=self.request.user)
        from platform_growth.models import PlatformAutomationRule
        from platform_growth.services.automation_engine import evaluate_rules

        evaluate_rules(
            PlatformAutomationRule.TriggerType.LEAD_CREATED,
            payload={
                "lead_id": lead.id,
                "source": getattr(lead, "source", ""),
                "status": getattr(lead, "status", ""),
                "full_name": getattr(lead, "full_name", ""),
                "email": getattr(lead, "email", ""),
            },
            user=self.request.user,
        )


class PlatformConversationViewSet(BasePlatformConversationViewSet):
    def get_queryset(self):
        qs = PlatformConversation.objects.select_related("lead").prefetch_related("messages").all()
        if is_god_mode(self.request.user):
            return qs
        if (getattr(self.request.user, "role", "") or "").upper() != "SBO":
            return qs.none()
        return qs.filter(lead__assigned_to=self.request.user)
