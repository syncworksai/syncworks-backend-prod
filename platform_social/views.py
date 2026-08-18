from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import (
    Collection,
    CollectionShare,
    EventMemberResponse,
    GroupEventInvitation,
    GroupMembership,
    SocialConnection,
    SocialEvent,
    SocialGroup,
)
from .serializers import (
    CollectionSerializer,
    CollectionShareSerializer,
    EventMemberResponseSerializer,
    GroupEventInvitationSerializer,
    GroupMembershipSerializer,
    SocialConnectionSerializer,
    SocialEventSerializer,
    SocialGroupSerializer,
    SocialUserSerializer,
)
from user_accounts.models import User


MANAGEMENT_ROLES = {
    GroupMembership.Role.OWNER,
    GroupMembership.Role.DIRECTOR,
    GroupMembership.Role.MANAGER,
}


def active_group_ids(user):
    return GroupMembership.objects.filter(
        user=user,
        status=GroupMembership.Status.ACTIVE,
    ).values_list("group_id", flat=True)


def managed_group_ids(user):
    return GroupMembership.objects.filter(
        user=user,
        status=GroupMembership.Status.ACTIVE,
        role__in=MANAGEMENT_ROLES,
    ).values_list("group_id", flat=True)


def can_manage_group(user, group_id):
    return GroupMembership.objects.filter(
        group_id=group_id,
        user=user,
        status=GroupMembership.Status.ACTIVE,
        role__in=MANAGEMENT_ROLES,
    ).exists()


def event_is_for_group(event, group_id):
    if event.organizer_group_id == group_id:
        return True
    return GroupEventInvitation.objects.filter(
        event=event,
        target_group_id=group_id,
        status=GroupEventInvitation.Status.ACCEPTED,
    ).exists()


class PeopleSearchViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = SocialUserSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        query = str(self.request.query_params.get("search") or "").strip()
        qs = User.objects.exclude(id=self.request.user.id).order_by("first_name", "last_name", "email")
        if query:
            qs = qs.filter(
                Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
                | Q(email__icontains=query)
                | Q(username__icontains=query)
            )
        else:
            qs = qs.none()
        return qs[:50]


class SocialConnectionViewSet(viewsets.ModelViewSet):
    serializer_class = SocialConnectionSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        return SocialConnection.objects.filter(
            Q(sender=self.request.user) | Q(recipient=self.request.user)
        ).select_related("sender", "recipient")

    def perform_create(self, serializer):
        recipient = serializer.validated_data["recipient"]
        if recipient == self.request.user:
            raise serializers.ValidationError("You cannot connect to yourself.")
        if SocialConnection.objects.filter(
            Q(sender=self.request.user, recipient=recipient)
            | Q(sender=recipient, recipient=self.request.user)
        ).exists():
            raise serializers.ValidationError("A connection already exists.")
        serializer.save(sender=self.request.user)

    def _respond(self, request, status_value):
        connection = self.get_object()
        if connection.recipient_id != request.user.id:
            return Response({"detail": "Only the recipient can respond."}, status=403)
        connection.status = status_value
        connection.responded_at = timezone.now()
        connection.save(update_fields=("status", "responded_at", "updated_at"))
        return Response(self.get_serializer(connection).data)

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        return self._respond(request, SocialConnection.Status.ACCEPTED)

    @action(detail=True, methods=["post"])
    def decline(self, request, pk=None):
        return self._respond(request, SocialConnection.Status.DECLINED)


class SocialGroupViewSet(viewsets.ModelViewSet):
    serializer_class = SocialGroupSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        group_ids = active_group_ids(self.request.user)
        return SocialGroup.objects.filter(
            Q(id__in=group_ids)
            | Q(created_by=self.request.user)
            | Q(visibility=SocialGroup.Visibility.PUBLIC)
        ).distinct().select_related("parent", "created_by")

    def perform_create(self, serializer):
        parent = serializer.validated_data.get("parent")
        if parent and not can_manage_group(self.request.user, parent.id):
            raise serializers.ValidationError("You cannot create a child group here.")
        group = serializer.save(created_by=self.request.user)
        GroupMembership.objects.get_or_create(
            group=group,
            user=self.request.user,
            defaults={
                "role": GroupMembership.Role.OWNER,
                "status": GroupMembership.Status.ACTIVE,
                "invited_by": self.request.user,
            },
        )

    def perform_update(self, serializer):
        group = self.get_object()
        if not can_manage_group(self.request.user, group.id):
            raise serializers.ValidationError("You cannot edit this group.")
        serializer.save()

    def perform_destroy(self, instance):
        if not can_manage_group(self.request.user, instance.id):
            raise serializers.ValidationError("You cannot archive this group.")
        instance.status = SocialGroup.Status.ARCHIVED
        instance.save(update_fields=("status", "updated_at"))


class GroupMembershipViewSet(viewsets.ModelViewSet):
    serializer_class = GroupMembershipSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        managed = managed_group_ids(self.request.user)
        return GroupMembership.objects.filter(
            Q(user=self.request.user) | Q(group_id__in=managed)
        ).select_related("user", "group", "invited_by")

    def perform_create(self, serializer):
        group = serializer.validated_data["group"]
        if not can_manage_group(self.request.user, group.id):
            raise serializers.ValidationError("You cannot invite members to this group.")
        user = serializer.validated_data["user"]
        if GroupMembership.objects.filter(group=group, user=user).exists():
            raise serializers.ValidationError("This person already has a membership record.")
        serializer.save(
            invited_by=self.request.user,
            status=GroupMembership.Status.INVITED,
        )

    def _respond(self, request, status_value):
        membership = self.get_object()
        if membership.user_id != request.user.id:
            return Response({"detail": "Only the invited member can respond."}, status=403)
        membership.status = status_value
        membership.responded_at = timezone.now()
        membership.save(update_fields=("status", "responded_at", "updated_at"))
        return Response(self.get_serializer(membership).data)

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        return self._respond(request, GroupMembership.Status.ACTIVE)

    @action(detail=True, methods=["post"])
    def decline(self, request, pk=None):
        return self._respond(request, GroupMembership.Status.DECLINED)


class SocialEventViewSet(viewsets.ModelViewSet):
    serializer_class = SocialEventSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        active_groups = active_group_ids(self.request.user)
        return SocialEvent.objects.filter(
            Q(created_by=self.request.user)
            | Q(organizer_group_id__in=active_groups)
            | Q(group_invitations__target_group_id__in=active_groups)
        ).distinct().select_related("organizer_group", "created_by")

    def perform_create(self, serializer):
        organizer_group = serializer.validated_data.get("organizer_group")
        if organizer_group and not can_manage_group(self.request.user, organizer_group.id):
            raise serializers.ValidationError("You cannot create events for this group.")
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        event = self.get_object()
        if event.created_by_id != self.request.user.id and not (
            event.organizer_group_id and can_manage_group(self.request.user, event.organizer_group_id)
        ):
            raise serializers.ValidationError("You cannot edit this event.")
        serializer.save(version=event.version + 1)

    def perform_destroy(self, instance):
        if instance.created_by_id != self.request.user.id and not (
            instance.organizer_group_id and can_manage_group(self.request.user, instance.organizer_group_id)
        ):
            raise serializers.ValidationError("You cannot cancel this event.")
        instance.status = SocialEvent.Status.CANCELLED
        instance.version += 1
        instance.save(update_fields=("status", "version", "updated_at"))


class GroupEventInvitationViewSet(viewsets.ModelViewSet):
    serializer_class = GroupEventInvitationSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        group_ids = active_group_ids(self.request.user)
        return GroupEventInvitation.objects.filter(
            Q(invited_by=self.request.user)
            | Q(target_group_id__in=group_ids)
            | Q(event__created_by=self.request.user)
        ).distinct().select_related("event", "target_group", "invited_by", "responded_by")

    def perform_create(self, serializer):
        event = serializer.validated_data["event"]
        target_group = serializer.validated_data["target_group"]
        if event.created_by_id != self.request.user.id and not (
            event.organizer_group_id and can_manage_group(self.request.user, event.organizer_group_id)
        ):
            raise serializers.ValidationError("You cannot invite groups to this event.")
        if event.organizer_group_id == target_group.id:
            raise serializers.ValidationError("The organizer group is already part of this event.")
        serializer.save(invited_by=self.request.user)

    def _respond(self, request, status_value):
        invitation = self.get_object()
        if not can_manage_group(request.user, invitation.target_group_id):
            return Response({"detail": "Only a group manager can respond."}, status=403)
        invitation.status = status_value
        invitation.responded_by = request.user
        invitation.responded_at = timezone.now()
        invitation.save(
            update_fields=(
                "status",
                "responded_by",
                "responded_at",
                "updated_at",
            )
        )
        return Response(self.get_serializer(invitation).data)

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        return self._respond(request, GroupEventInvitation.Status.ACCEPTED)

    @action(detail=True, methods=["post"])
    def decline(self, request, pk=None):
        return self._respond(request, GroupEventInvitation.Status.DECLINED)


class EventMemberResponseViewSet(viewsets.ModelViewSet):
    serializer_class = EventMemberResponseSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        return EventMemberResponse.objects.filter(
            Q(user=self.request.user)
            | Q(group_id__in=managed_group_ids(self.request.user))
        ).distinct()

    def perform_create(self, serializer):
        group = serializer.validated_data["group"]
        event = serializer.validated_data["event"]
        if not GroupMembership.objects.filter(
            group=group,
            user=self.request.user,
            status=GroupMembership.Status.ACTIVE,
        ).exists():
            raise serializers.ValidationError("You are not an active member of this group.")
        if not event_is_for_group(event, group.id):
            raise serializers.ValidationError("This event has not been accepted by your group.")

        existing = EventMemberResponse.objects.filter(
            event=event,
            group=group,
            user=self.request.user,
        ).first()
        if existing:
            existing.response = serializer.validated_data["response"]
            existing.responded_at = timezone.now()
            existing.save(update_fields=("response", "responded_at", "updated_at"))
            serializer.instance = existing
            return

        serializer.save(user=self.request.user, responded_at=timezone.now())

    def perform_update(self, serializer):
        response = self.get_object()
        if response.user_id != self.request.user.id:
            raise serializers.ValidationError("Only the member can change this response.")
        serializer.save(responded_at=timezone.now())


class CollectionViewSet(viewsets.ModelViewSet):
    serializer_class = CollectionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        group_ids = active_group_ids(self.request.user)
        return Collection.objects.filter(
            Q(group_id__in=group_ids) | Q(shares__user=self.request.user)
        ).distinct().prefetch_related("shares__user")

    def perform_create(self, serializer):
        group = serializer.validated_data["group"]
        if not can_manage_group(self.request.user, group.id):
            raise serializers.ValidationError("You cannot create collections for this group.")
        event = serializer.validated_data.get("event")
        if event and not event_is_for_group(event, group.id):
            raise serializers.ValidationError("This event is not available to this group.")
        collection = serializer.save(created_by=self.request.user)
        members = GroupMembership.objects.filter(group=group, status=GroupMembership.Status.ACTIVE)
        if collection.split_method == Collection.SplitMethod.EQUAL and members.exists():
            amount = collection.total_amount_cents // members.count()
            remainder = collection.total_amount_cents - (amount * members.count())
            for index, membership in enumerate(members.order_by("id")):
                CollectionShare.objects.create(
                    collection=collection,
                    user=membership.user,
                    amount_due_cents=amount + (remainder if index == 0 else 0),
                )

    def perform_update(self, serializer):
        collection = self.get_object()
        if not can_manage_group(self.request.user, collection.group_id):
            raise serializers.ValidationError("You cannot edit this collection.")
        serializer.save()

    def perform_destroy(self, instance):
        if not can_manage_group(self.request.user, instance.group_id):
            raise serializers.ValidationError("You cannot cancel this collection.")
        instance.status = Collection.Status.CANCELLED
        instance.save(update_fields=("status", "updated_at"))


class CollectionShareViewSet(viewsets.ModelViewSet):
    serializer_class = CollectionShareSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        managed = managed_group_ids(self.request.user)
        return CollectionShare.objects.filter(
            Q(user=self.request.user) | Q(collection__group_id__in=managed)
        ).select_related("collection", "user")

    def perform_create(self, serializer):
        collection = serializer.validated_data["collection"]
        if not can_manage_group(self.request.user, collection.group_id):
            raise serializers.ValidationError("You cannot manage collection shares for this group.")
        serializer.save(status=CollectionShare.Status.PENDING)
