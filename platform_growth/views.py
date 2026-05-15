from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission, IsAuthenticated
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
from platform_growth.services.automation_engine import evaluate_rules, seed_system_templates
from platform_growth.services.funnel import lead_status_breakdown
from platform_growth.services.meta import record_meta_event, record_possible_message
from platform_growth.services.meta_oauth import (
    MetaOAuthConfigurationError,
    MetaOAuthRequestError,
    build_authorization_url,
    choose_connection_account,
    exchange_code_for_access_token,
    expires_at_from_token_payload,
    fetch_meta_accounts,
    fetch_meta_profile,
    get_meta_oauth_config,
)
from platform_growth.services.oauth_state import generate_state_token, is_state_expired
from platform_growth.services.posting import build_outbound_payload
from user_accounts.permissions import IsGodMode


class IsGodModeOrSBO(BasePermission):
    message = "Not allowed."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False

        from user_accounts.services.god_mode import is_god_mode

        if is_god_mode(user):
            return True

        return (getattr(user, "role", "") or "").upper() == "SBO"


def _is_god_mode_user(user) -> bool:
    from user_accounts.services.god_mode import is_god_mode

    return is_god_mode(user)


def _is_sbo_user(user) -> bool:
    return (getattr(user, "role", "") or "").upper() == "SBO"


def _is_internal_admin_user(user) -> bool:
    return bool(getattr(user, "is_platform_admin", False))


def _is_growth_connection_admin_user(user) -> bool:
    return _is_god_mode_user(user) or _is_internal_admin_user(user)


class IsGrowthConnectionAdminOrSBO(BasePermission):
    message = "Not allowed."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False

        if _is_growth_connection_admin_user(user):
            return True

        return _is_sbo_user(user)


def _model_has_field(model, field_name: str) -> bool:
    try:
        return any(field.name == field_name for field in model._meta.get_fields())
    except Exception:
        return False


def _safe_user_scoped_queryset(queryset, user):
    """
    Stage 11 safety:
    - God Mode can see all.
    - SBO can only see records scoped to created_by when the model supports it.
    - If a model has no owner field yet, do NOT expose platform-wide data to SBO.
    """
    if _is_god_mode_user(user):
        return queryset

    if not _is_sbo_user(user):
        return queryset.none()

    model = getattr(queryset, "model", None)
    if model is not None and _model_has_field(model, "created_by"):
        return queryset.filter(created_by=user)

    return queryset.none()


def _serializer_save_with_created_by(serializer, user):
    model = getattr(getattr(serializer, "Meta", None), "model", None)
    if model is not None and _model_has_field(model, "created_by"):
        return serializer.save(created_by=user)
    return serializer.save()


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
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated, IsGodModeOrSBO]
    serializer_class = PlatformLeadSerializer
    queryset = PlatformLead.objects.all().order_by("-last_activity_at", "-created_at")

    def get_queryset(self):
        return _safe_user_scoped_queryset(super().get_queryset(), self.request.user)

    def perform_create(self, serializer):
        lead = _serializer_save_with_created_by(serializer, self.request.user)

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

    def perform_update(self, serializer):
        current = self.get_object()
        old_status = current.status

        lead = serializer.save()

        if old_status != lead.status:
            evaluate_rules(
                PlatformAutomationRule.TriggerType.LEAD_STATUS_CHANGED,
                payload={
                    "lead_id": lead.id,
                    "old_status": old_status,
                    "new_status": lead.status,
                    "source": getattr(lead, "source", ""),
                    "full_name": getattr(lead, "full_name", ""),
                    "email": getattr(lead, "email", ""),
                },
                user=self.request.user,
            )


class PlatformConversationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, IsGodModeOrSBO]
    serializer_class = PlatformConversationSerializer
    queryset = PlatformConversation.objects.select_related("lead").prefetch_related("messages").all()

    def get_queryset(self):
        qs = super().get_queryset()

        if _is_god_mode_user(self.request.user):
            return qs

        if not _is_sbo_user(self.request.user):
            return qs.none()

        if _model_has_field(PlatformLead, "created_by"):
            return qs.filter(lead__created_by=self.request.user)

        return qs.none()

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
    permission_classes = [IsAuthenticated, IsGrowthConnectionAdminOrSBO]
    serializer_class = GrowthChannelConnectionSerializer
    queryset = GrowthChannelConnection.objects.all().order_by("provider", "-created_at")

    def get_queryset(self):
        if _is_growth_connection_admin_user(self.request.user):
            return super().get_queryset()
        return _safe_user_scoped_queryset(super().get_queryset(), self.request.user)

    def _user_can_manage_connections(self) -> bool:
        return _is_growth_connection_admin_user(self.request.user)

    def create(self, request, *args, **kwargs):
        if not self._user_can_manage_connections():
            return Response(
                {"detail": "OAuth channel connections must be created server-side."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        if not self._user_can_manage_connections():
            return Response(
                {"detail": "OAuth channel connections must be updated server-side."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        if not self._user_can_manage_connections():
            return Response(
                {"detail": "OAuth channel connections must be updated server-side."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if not self._user_can_manage_connections():
            return Response(
                {"detail": "OAuth channel connections must be removed server-side."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().destroy(request, *args, **kwargs)

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
    permission_classes = [IsAuthenticated, IsGodModeOrSBO]
    serializer_class = GrowthContentDraftSerializer
    queryset = GrowthContentDraft.objects.all().order_by("-updated_at", "-created_at")

    def get_queryset(self):
        return _safe_user_scoped_queryset(super().get_queryset(), self.request.user)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=False, methods=["post"], url_path="starter")
    def starter(self, request):
        starter_type = request.data.get("starter_type")
        starter_content = {
            "lead_follow_up": {
                "title": "Lead Follow-Up Draft",
                "body": "Thanks for reaching out — we can help. Want to get on the schedule?",
            },
            "review_request": {
                "title": "Review Request Draft",
                "body": "Thanks again for choosing us. If we earned it, a quick review helps your small business grow.",
            },
            "weekly_tip": {
                "title": "Weekly Service Tip Draft",
                "body": "Quick service tip: small maintenance today can prevent bigger repairs later. Need help? Send us a request.",
            },
            "promo": {
                "title": "Service Promo Draft",
                "body": "Booking this week? Ask about our fast-turnaround service slots.",
            },
        }

        content = starter_content.get(starter_type)
        if content is None:
            return Response({"detail": "Invalid starter_type."}, status=status.HTTP_400_BAD_REQUEST)

        draft = GrowthContentDraft.objects.create(
            title=content["title"],
            body=content["body"],
            status=GrowthContentDraft.Status.DRAFT,
            source="STARTER",
            metadata={
                "safe_mode": True,
                "starter_type": starter_type,
                "no_external_post": True,
                "created_from": "sbo_growth_os_starter",
            },
            created_by=request.user,
        )

        return Response(self.get_serializer(draft).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def queue(self, request, pk=None):
        draft = self.get_object()
        channel_connection_id = request.data.get("channel_connection")
        scheduled_for = request.data.get("scheduled_for")

        channel_connection = None
        if channel_connection_id:
            channel_connection = GrowthChannelConnection.objects.filter(id=channel_connection_id).first()
            if channel_connection is None:
                return Response({"detail": "channel_connection not found."}, status=status.HTTP_400_BAD_REQUEST)

            if not _is_god_mode_user(request.user) and getattr(channel_connection, "created_by_id", None) != request.user.id:
                return Response({"detail": "channel_connection not found."}, status=status.HTTP_400_BAD_REQUEST)

        if channel_connection is None:
            channel_connection, _ = GrowthChannelConnection.objects.get_or_create(
                provider=GrowthChannelConnection.Provider.META,
                external_account_id="safe-mode",
                created_by=request.user,
                defaults={
                    "account_label": "Manual / Safe Mode",
                    "status": GrowthChannelConnection.Status.CONNECTED,
                    "metadata": {"safe_mode": True, "internal_placeholder": True},
                },
            )

            if channel_connection.status != GrowthChannelConnection.Status.CONNECTED:
                channel_connection.status = GrowthChannelConnection.Status.CONNECTED
                channel_connection.save(update_fields=["status", "updated_at"])

        queue_item = GrowthContentQueueItem.objects.create(
            draft=draft,
            channel_connection=channel_connection,
            status=GrowthContentQueueItem.Status.QUEUED,
            scheduled_for=scheduled_for or None,
            metadata={
                "safe_mode": True,
                "no_external_post": True,
            },
            created_by=request.user,
        )

        return Response(GrowthContentQueueItemSerializer(queue_item).data, status=status.HTTP_201_CREATED)


class GrowthContentQueueItemViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsGodModeOrSBO]
    serializer_class = GrowthContentQueueItemSerializer
    queryset = GrowthContentQueueItem.objects.select_related("draft", "channel_connection").all().order_by("scheduled_for", "-created_at")

    def get_queryset(self):
        return _safe_user_scoped_queryset(super().get_queryset(), self.request.user)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["post"], url_path="simulate-post")
    def simulate_post(self, request, pk=None):
        queue_item = self.get_object()
        queue_item.status = GrowthContentQueueItem.Status.POSTED
        queue_item.posted_at = timezone.now()

        metadata = dict(queue_item.metadata or {})
        metadata.update(
            {
                "simulated_post": True,
                "no_external_post": True,
            }
        )
        queue_item.metadata = metadata
        queue_item.save(update_fields=["status", "posted_at", "metadata", "updated_at"])

        return Response(self.get_serializer(queue_item).data)


class GrowthAutomationRecipeViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsGodModeOrSBO]
    serializer_class = GrowthAutomationRecipeSerializer
    queryset = GrowthAutomationRecipe.objects.all().order_by("name")

    def get_queryset(self):
        if _is_god_mode_user(self.request.user):
            return super().get_queryset()

        if _is_sbo_user(self.request.user):
            qs = super().get_queryset()
            if _model_has_field(GrowthAutomationRecipe, "created_by"):
                return qs.filter(created_by=self.request.user)
            return qs

        return super().get_queryset().none()

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class GrowthScheduledPostJobViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsGodModeOrSBO]
    serializer_class = GrowthScheduledPostJobSerializer
    queryset = GrowthScheduledPostJob.objects.select_related("queue_item").all().order_by("run_at", "-created_at")

    def get_queryset(self):
        qs = super().get_queryset()

        if _is_god_mode_user(self.request.user):
            return qs

        if not _is_sbo_user(self.request.user):
            return qs.none()

        if _model_has_field(GrowthScheduledPostJob, "created_by"):
            return qs.filter(created_by=self.request.user)

        if _model_has_field(GrowthContentQueueItem, "created_by"):
            return qs.filter(queue_item__created_by=self.request.user)

        return qs.none()

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
    permission_classes = [IsAuthenticated, IsGrowthConnectionAdminOrSBO]

    VALID_REQUESTED_CHANNELS = {"facebook", "instagram", "meta"}

    def post(self, request):
        requested_channel = str(
            request.data.get("provider")
            or request.data.get("channel")
            or "facebook"
        ).strip().lower()

        if requested_channel not in self.VALID_REQUESTED_CHANNELS:
            return Response(
                {"detail": "Invalid provider. Supported providers: facebook, instagram."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if requested_channel == "meta":
            requested_channel = "facebook"

        try:
            config = get_meta_oauth_config(require_secret=False)
        except MetaOAuthConfigurationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        state_token = generate_state_token()
        state_obj = GrowthOAuthState.objects.create(
            provider=GrowthChannelConnection.Provider.META,
            state=state_token,
            redirect_uri=config.redirect_uri,
            metadata={
                "requested_channel": requested_channel,
                "scopes": config.scopes,
                "graph_api_version": config.graph_api_version,
                "oauth_provider": "meta",
                "no_external_post": True,
            },
            created_by=request.user,
        )

        try:
            authorization_url = build_authorization_url(state=state_obj.state)
        except MetaOAuthConfigurationError as exc:
            state_obj.status = GrowthOAuthState.Status.CANCELED
            state_obj.save(update_fields=["status", "updated_at"])
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "authorization_url": authorization_url,
                "state": state_obj.state,
                "provider": requested_channel,
            }
        )


class OAuthMetaCallbackAPIView(APIView):
    permission_classes = [IsAuthenticated, IsGrowthConnectionAdminOrSBO]

    def get(self, request):
        code = str(request.query_params.get("code") or "").strip()
        state_token = str(request.query_params.get("state") or "").strip()

        if not code or not state_token:
            return Response({"detail": "code and state are required."}, status=status.HTTP_400_BAD_REQUEST)

        state_obj = GrowthOAuthState.objects.filter(state=state_token, provider=GrowthChannelConnection.Provider.META).first()
        if state_obj is None:
            return Response({"detail": "Invalid OAuth state."}, status=status.HTTP_400_BAD_REQUEST)

        if state_obj.status != GrowthOAuthState.Status.PENDING:
            return Response({"detail": "OAuth state is not pending."}, status=status.HTTP_400_BAD_REQUEST)

        if is_state_expired(state_obj.expires_at):
            state_obj.status = GrowthOAuthState.Status.EXPIRED
            state_obj.save(update_fields=["status", "updated_at"])
            return Response({"detail": "OAuth state has expired."}, status=status.HTTP_400_BAD_REQUEST)

        owner = state_obj.created_by
        if owner is None:
            return Response({"detail": "OAuth state owner is missing."}, status=status.HTTP_400_BAD_REQUEST)

        if getattr(owner, "id", None) != getattr(request.user, "id", None):
            return Response({"detail": "OAuth state does not belong to this user."}, status=status.HTTP_403_FORBIDDEN)

        requested_channel = str((state_obj.metadata or {}).get("requested_channel") or "facebook").strip().lower()

        try:
            token_payload = exchange_code_for_access_token(code=code)
            user_access_token = str(token_payload.get("access_token") or "").strip()
            profile = fetch_meta_profile(access_token=user_access_token)
            accounts_payload = fetch_meta_accounts(access_token=user_access_token)
            account = choose_connection_account(
                user_access_token=user_access_token,
                profile=profile,
                accounts_payload=accounts_payload,
            )
        except MetaOAuthConfigurationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except MetaOAuthRequestError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        existing_meta_connection = GrowthChannelConnection.objects.filter(
            provider=GrowthChannelConnection.Provider.META,
            external_account_id=account.external_account_id,
        ).first()

        if existing_meta_connection is not None and existing_meta_connection.created_by_id not in (None, owner.id):
            return Response(
                {"detail": "This Meta account is already connected to another user."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        scopes = list((state_obj.metadata or {}).get("scopes") or get_meta_oauth_config(require_secret=False).scopes)
        base_connection_defaults = {
            "account_label": account.account_label,
            "status": GrowthChannelConnection.Status.CONNECTED,
            "scopes": scopes,
            "connected_at": timezone.now(),
            "disconnected_at": None,
            "last_error": "",
            "metadata": account.metadata,
            "created_by": owner,
        }

        meta_connection, _ = GrowthChannelConnection.objects.update_or_create(
            provider=GrowthChannelConnection.Provider.META,
            external_account_id=account.external_account_id,
            defaults=base_connection_defaults,
        )

        target_connection = meta_connection
        target_provider = GrowthChannelConnection.Provider.META

        if requested_channel == "instagram":
            selected_account = account.metadata.get("selected_account") or {}
            ig_account = selected_account.get("instagram_business_account") or account.metadata.get("instagram_business_account") or {}
            ig_id = str(ig_account.get("id") or "").strip()

            if not ig_id:
                return Response(
                    {"detail": "No Instagram Business account is connected to this Facebook Page."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            existing_ig_connection = GrowthChannelConnection.objects.filter(
                provider=GrowthChannelConnection.Provider.INSTAGRAM,
                external_account_id=ig_id,
            ).first()

            if existing_ig_connection is not None and existing_ig_connection.created_by_id not in (None, owner.id):
                return Response(
                    {"detail": "This Instagram account is already connected to another user."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            ig_username = str(ig_account.get("username") or ig_account.get("name") or ig_id).strip()
            ig_label = ig_username if ig_username.startswith("@") else f"@{ig_username}"

            instagram_metadata = {
                **account.metadata,
                "parent_meta_connection_id": meta_connection.id,
                "facebook_page_id": account.external_account_id,
                "instagram_business_account": ig_account,
                "account_kind": "instagram_business",
                "oauth_provider": "meta",
                "no_external_post": True,
            }

            instagram_defaults = {
                **base_connection_defaults,
                "account_label": ig_label,
                "metadata": instagram_metadata,
            }

            target_connection, _ = GrowthChannelConnection.objects.update_or_create(
                provider=GrowthChannelConnection.Provider.INSTAGRAM,
                external_account_id=ig_id,
                defaults=instagram_defaults,
            )
            target_provider = GrowthChannelConnection.Provider.INSTAGRAM

        target_connection.oauth_tokens.filter(is_active=True).update(is_active=False, updated_at=timezone.now())
        token = GrowthOAuthToken.objects.create(
            connection=target_connection,
            provider=target_provider,
            token_type=str(token_payload.get("token_type") or "bearer"),
            access_token=account.access_token,
            refresh_token="",
            expires_at=expires_at_from_token_payload(token_payload),
            scope=str(token_payload.get("scope") or ",".join(scopes)),
            is_active=True,
            metadata={
                "meta_user_id": profile.get("id"),
                "account_kind": target_connection.metadata.get("account_kind"),
                "parent_meta_connection_id": target_connection.metadata.get("parent_meta_connection_id"),
                "facebook_page_id": target_connection.metadata.get("facebook_page_id"),
                "requested_channel": requested_channel,
                "no_external_post": True,
            },
            created_by=owner,
        )

        if target_connection.id != meta_connection.id:
            meta_connection.oauth_tokens.filter(is_active=True).update(is_active=False, updated_at=timezone.now())
            GrowthOAuthToken.objects.create(
                connection=meta_connection,
                provider=GrowthChannelConnection.Provider.META,
                token_type=str(token_payload.get("token_type") or "bearer"),
                access_token=account.access_token,
                refresh_token="",
                expires_at=expires_at_from_token_payload(token_payload),
                scope=str(token_payload.get("scope") or ",".join(scopes)),
                is_active=True,
                metadata={
                    "meta_user_id": profile.get("id"),
                    "account_kind": meta_connection.metadata.get("account_kind"),
                    "requested_channel": requested_channel,
                    "no_external_post": True,
                },
                created_by=owner,
            )

        state_obj.status = GrowthOAuthState.Status.USED
        state_obj.used_at = timezone.now()
        state_metadata = dict(state_obj.metadata or {})
        state_metadata.update(
            {
                "connection_id": target_connection.id,
                "meta_connection_id": meta_connection.id,
                "token_id": token.id,
                "requested_channel": requested_channel,
            }
        )
        state_obj.metadata = state_metadata
        state_obj.save(update_fields=["status", "used_at", "metadata", "updated_at"])

        return Response(
            {
                "ok": True,
                "state": state_obj.state,
                "requested_channel": requested_channel,
                "connection": {
                    "id": target_connection.id,
                    "provider": target_connection.provider,
                    "account_label": target_connection.account_label,
                    "external_account_id": target_connection.external_account_id,
                    "status": target_connection.status,
                    "scopes": target_connection.scopes,
                },
                "meta_connection": {
                    "id": meta_connection.id,
                    "provider": meta_connection.provider,
                    "account_label": meta_connection.account_label,
                    "external_account_id": meta_connection.external_account_id,
                    "status": meta_connection.status,
                },
                "token": {
                    "id": token.id,
                    "provider": token.provider,
                    "token_type": token.token_type,
                    "expires_at": token.expires_at,
                    "scope": token.scope,
                    "is_active": token.is_active,
                },
                "no_external_post": True,
            }
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
                        saved_messages = record_possible_message(change)

                        if saved_messages:
                            evaluate_rules(
                                PlatformAutomationRule.TriggerType.INBOUND_MESSAGE_RECEIVED,
                                payload={"object": object_name, "change": change, "entry_id": entry.get("id")},
                                user=None,
                            )

        if not created_events:
            event = record_meta_event(payload, event_type=f"meta.{object_name}.raw")
            created_events.append(event.id)

        return Response({"ok": True, "event_ids": created_events}, status=status.HTTP_202_ACCEPTED)