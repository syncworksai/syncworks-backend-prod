from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from platform_growth.models import (
    GrowthAutomationRecipe,
    GrowthChannelConnection,
    GrowthContentDraft,
    GrowthContentQueueItem,
    GrowthOAuthState,
    GrowthOAuthToken,
    GrowthScheduledPostJob,
    PlatformActivationEvent,
    PlatformAutomationExecution,
    PlatformAutomationFlow,
    PlatformAutomationRule,
    PlatformCampaign,
    PlatformContent,
    PlatformConversation,
    PlatformLead,
    PlatformMessage,
)
from platform_growth.serializers import (
    GrowthAutomationRecipeSerializer,
    GrowthChannelConnectionSerializer,
    GrowthContentDraftSerializer,
    GrowthContentQueueItemSerializer,
    GrowthOAuthStateSerializer,
    GrowthOAuthTokenSerializer,
    GrowthScheduledPostJobSerializer,
    PlatformAutomationExecutionSerializer,
    PlatformAutomationFlowSerializer,
    PlatformAutomationRuleSerializer,
    PlatformCampaignSerializer,
    PlatformContentSerializer,
    PlatformConversationSerializer,
    PlatformLeadSerializer,
    PlatformMessageSerializer,
)
from platform_growth.services.automation_engine import seed_system_templates
from platform_growth.services.funnel import lead_status_breakdown
from platform_growth.services.meta import record_meta_event, record_possible_message
from platform_growth.services.oauth_state import generate_state_token
from platform_growth.services.posting import build_outbound_payload
from user_accounts.permissions import IsGodMode


def build_meta_authorization_url(*, state: str, redirect_uri: str) -> str:
    return ""


def exchange_code_for_token(*, code: str, redirect_uri: str) -> dict:
    raise ValueError("Meta OAuth setup is paused.")


def fetch_meta_account_metadata(access_token: str) -> dict:
    return {}


def normalize_meta_error(error: str) -> str:
    return str(error or "Meta OAuth setup is paused.")


class PlatformGrowthDashboardAPIView(APIView):
    permission_classes = [IsAuthenticated, IsGodMode]

    def get(self, request):
        today = timezone.now()
        data = {
            "campaigns": PlatformCampaign.objects.count(),
            "active_campaigns": PlatformCampaign.objects.filter(status=PlatformCampaign.Status.ACTIVE).count(),
            "content_items": PlatformContent.objects.count(),
            "leads": PlatformLead.objects.count(),
            "lead_status": lead_status_breakdown(),
            "open_conversations": PlatformConversation.objects.exclude(status=PlatformConversation.Status.CLOSED).count(),
            "messages_last_24h": PlatformMessage.objects.filter(sent_at__gte=today - timedelta(hours=24)).count(),
            "events_last_24h": PlatformActivationEvent.objects.filter(created_at__gte=today - timedelta(hours=24)).count(),
            "growth_channels": GrowthChannelConnection.objects.count(),
            "growth_drafts": GrowthContentDraft.objects.count(),
            "growth_queue_items": GrowthContentQueueItem.objects.count(),
        }
        return Response(data)


class PlatformCampaignViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsGodMode]
    serializer_class = PlatformCampaignSerializer
    queryset = PlatformCampaign.objects.all().order_by("-created_at")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class PlatformContentViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsGodMode]
    serializer_class = PlatformContentSerializer
    queryset = PlatformContent.objects.select_related("campaign").all().order_by("-created_at")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class PlatformLeadViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated, IsGodMode]
    serializer_class = PlatformLeadSerializer
    queryset = PlatformLead.objects.all().order_by("-last_activity_at", "-created_at")


class PlatformConversationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, IsGodMode]
    serializer_class = PlatformConversationSerializer
    queryset = PlatformConversation.objects.select_related("lead").prefetch_related("messages").all()

    @action(detail=True, methods=["get"])
    def messages(self, request, pk=None):
        convo = self.get_object()
        qs = convo.messages.all().order_by("sent_at", "id")
        return Response(PlatformMessageSerializer(qs, many=True).data)

    @action(detail=True, methods=["post"])
    def reply(self, request, pk=None):
        convo = self.get_object()
        text = str(request.data.get("text") or "").strip()
        if not text:
            return Response({"detail": "text is required"}, status=status.HTTP_400_BAD_REQUEST)

        outbound_payload = build_outbound_payload(text)
        msg = PlatformMessage.objects.create(
            conversation=convo,
            direction=PlatformMessage.Direction.OUTBOUND,
            text=text,
            raw_payload=outbound_payload,
        )
        convo.last_message_at = msg.sent_at
        convo.save(update_fields=["last_message_at", "updated_at"])
        return Response(PlatformMessageSerializer(msg).data, status=status.HTTP_201_CREATED)


class PlatformAutomationFlowViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsGodMode]
    serializer_class = PlatformAutomationFlowSerializer
    queryset = PlatformAutomationFlow.objects.all().order_by("name")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class GrowthChannelConnectionViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsGodMode]
    serializer_class = GrowthChannelConnectionSerializer
    queryset = GrowthChannelConnection.objects.all().order_by("provider", "-created_at")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["post"])
    def disconnect(self, request, pk=None):
        conn = self.get_object()
        conn.status = GrowthChannelConnection.Status.DISCONNECTED
        conn.disconnected_at = timezone.now()
        conn.save(update_fields=["status", "disconnected_at", "updated_at"])
        conn.oauth_tokens.filter(is_active=True).update(is_active=False, updated_at=timezone.now())
        return Response(self.get_serializer(conn).data)


class GrowthOAuthStateViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsGodMode]
    serializer_class = GrowthOAuthStateSerializer
    queryset = GrowthOAuthState.objects.all().order_by("-created_at")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["post"])
    def mark_used(self, request, pk=None):
        state_obj = self.get_object()
        state_obj.status = GrowthOAuthState.Status.USED
        state_obj.used_at = timezone.now()
        state_obj.save(update_fields=["status", "used_at", "updated_at"])
        return Response(self.get_serializer(state_obj).data)


class GrowthOAuthTokenViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, IsGodMode]
    serializer_class = GrowthOAuthTokenSerializer
    queryset = GrowthOAuthToken.objects.select_related("connection").all().order_by("-created_at")


class GrowthContentDraftViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsGodMode]
    serializer_class = GrowthContentDraftSerializer
    queryset = GrowthContentDraft.objects.all().order_by("-updated_at", "-created_at")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class GrowthContentQueueItemViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsGodMode]
    serializer_class = GrowthContentQueueItemSerializer
    queryset = GrowthContentQueueItem.objects.select_related("draft", "channel_connection").all().order_by("scheduled_for", "-created_at")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class GrowthAutomationRecipeViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsGodMode]
    serializer_class = GrowthAutomationRecipeSerializer
    queryset = GrowthAutomationRecipe.objects.all().order_by("name")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class GrowthScheduledPostJobViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsGodMode]
    serializer_class = GrowthScheduledPostJobSerializer
    queryset = GrowthScheduledPostJob.objects.select_related("queue_item").all().order_by("run_at", "-created_at")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class PlatformAutomationRuleViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsGodMode]
    serializer_class = PlatformAutomationRuleSerializer
    queryset = PlatformAutomationRule.objects.all().order_by("name", "-created_at")

    def get_queryset(self):
        seed_system_templates(user=self.request.user)
        return super().get_queryset()

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["post"])
    def run_test(self, request, pk=None):
        rule = self.get_object()
        if rule.status != PlatformAutomationRule.Status.ACTIVE:
            return Response({"detail": "Rule is not active or did not match."}, status=status.HTTP_400_BAD_REQUEST)

        payload = request.data if isinstance(request.data, dict) else {}

        from platform_growth.services.automation_engine import execute_rule

        execution = execute_rule(rule, payload=payload, user=request.user)
        return Response(PlatformAutomationExecutionSerializer(execution).data)


class PlatformAutomationExecutionViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, IsGodMode]
    serializer_class = PlatformAutomationExecutionSerializer
    queryset = PlatformAutomationExecution.objects.select_related("rule").all().order_by("-created_at")


class OAuthMetaStartAPIView(APIView):
    permission_classes = [IsAuthenticated, IsGodMode]

    def post(self, request):
        return Response(
            {
                "detail": "Meta OAuth setup is paused. Configure platform_growth.services.meta_oauth before enabling this endpoint."
            },
            status=status.HTTP_501_NOT_IMPLEMENTED,
        )


class OAuthMetaCallbackAPIView(APIView):
    permission_classes = [IsAuthenticated, IsGodMode]

    def get(self, request):
        return Response(
            {
                "detail": "Meta OAuth setup is paused. Configure platform_growth.services.meta_oauth before enabling this endpoint."
            },
            status=status.HTTP_501_NOT_IMPLEMENTED,
        )


class MetaWebhookVerificationAPIView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        mode = request.query_params.get("hub.mode")
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge")

        expected = getattr(settings, "META_WEBHOOK_VERIFY_TOKEN", "")
        if mode == "subscribe" and token and expected and token == expected and challenge:
            return Response(challenge)
        return Response({"detail": "verification_failed"}, status=status.HTTP_403_FORBIDDEN)


class MetaWebhookEventAPIView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        payload = request.data if isinstance(request.data, dict) else {}
        object_name = str(payload.get("object") or "meta")

        created_events = []
        entry_items = payload.get("entry")
        if isinstance(entry_items, list):
            for entry in entry_items:
                if not isinstance(entry, dict):
                    continue
                event = record_meta_event(entry, event_type=f"meta.{object_name}.entry")
                created_events.append(event.id)

                changes = entry.get("changes")
                if isinstance(changes, list):
                    for idx, change in enumerate(changes):
                        if not isinstance(change, dict):
                            continue
                        record_meta_event(change, event_type=f"meta.{object_name}.change.{idx}")
                        record_possible_message(change)

        if not created_events:
            event = record_meta_event(payload, event_type=f"meta.{object_name}.raw")
            created_events.append(event.id)

        return Response({"ok": True, "event_ids": created_events}, status=status.HTTP_202_ACCEPTED)