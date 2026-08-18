from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from .communication_models import SocialMessage
from .communication_serializers import SocialMessageSerializer
from .models import GroupMembership
from .views import MANAGEMENT_ROLES, event_is_for_group


class SocialMessageViewSet(viewsets.ModelViewSet):
    serializer_class = SocialMessageSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def _active_membership(self, group_id):
        return GroupMembership.objects.filter(
            group_id=group_id,
            user=self.request.user,
            status=GroupMembership.Status.ACTIVE,
        ).first()

    def get_queryset(self):
        active_groups = GroupMembership.objects.filter(
            user=self.request.user,
            status=GroupMembership.Status.ACTIVE,
        ).values_list("group_id", flat=True)
        queryset = SocialMessage.objects.filter(
            group_id__in=active_groups,
            deleted_at__isnull=True,
        ).select_related("sender", "group", "event")

        group_id = self.request.query_params.get("group")
        if group_id:
            queryset = queryset.filter(group_id=group_id)

        event_value = self.request.query_params.get("event")
        if event_value == "none":
            queryset = queryset.filter(event__isnull=True)
        elif event_value:
            queryset = queryset.filter(event_id=event_value)

        return queryset.order_by("created_at", "id")

    def perform_create(self, serializer):
        group = serializer.validated_data["group"]
        membership = self._active_membership(group.id)
        if not membership:
            raise serializers.ValidationError("You must be an active member of this group to post in its chat.")

        event = serializer.validated_data.get("event")
        if event and not event_is_for_group(event, group.id):
            raise serializers.ValidationError("This event is not active for this group.")

        kind = serializer.validated_data.get("kind", SocialMessage.Kind.CHAT)
        if kind == SocialMessage.Kind.ANNOUNCEMENT and membership.role not in MANAGEMENT_ROLES:
            raise serializers.ValidationError("Only a group owner, director, or manager can post announcements.")
        if kind == SocialMessage.Kind.SYSTEM:
            raise serializers.ValidationError("System messages cannot be created manually.")

        serializer.save(sender=self.request.user)

    def perform_update(self, serializer):
        message = self.get_object()
        if message.sender_id != self.request.user.id:
            raise serializers.ValidationError("You can only edit your own message.")
        if "group" in serializer.validated_data or "event" in serializer.validated_data or "kind" in serializer.validated_data:
            raise serializers.ValidationError("Message scope and type cannot be changed after posting.")
        serializer.save(edited_at=timezone.now())
