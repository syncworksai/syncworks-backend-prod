from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from personal_calendar.models import PersonalCalendarEvent

from .models import (
    Collection,
    CollectionShare,
    Connection,
    EventMemberResponse,
    GroupEventInvitation,
    GroupMembership,
    SocialEvent,
    SocialGroup,
)
from .serializers import (
    CollectionSerializer,
    CollectionShareSerializer,
    ConnectionSerializer,
    EventMemberResponseSerializer,
    GroupEventInvitationSerializer,
    GroupMembershipSerializer,
    SocialEventSerializer,
    SocialGroupSerializer,
    SocialUserSerializer,
)

User = get_user_model()
MANAGEMENT_ROLES = (
    GroupMembership.Role.OWNER,
    GroupMembership.Role.DIRECTOR,
    GroupMembership.Role.MANAGER,
)


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
    if not group_id:
        return False
    return GroupMembership.objects.filter(
        user=user,
        group_id=group_id,
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


def accepted_event_group_ids(event):
    group_ids = set()
    if event.organizer_group_id:
        group_ids.add(event.organizer_group_id)
    group_ids.update(
        GroupEventInvitation.objects.filter(
            event=event,
            status=GroupEventInvitation.Status.ACCEPTED,
        ).values_list("target_group_id", flat=True)
    )
    return group_ids


def event_participant_user_ids(event):
    group_ids = accepted_event_group_ids(event)
    if not group_ids:
        return {event.created_by_id}
    return set(
        GroupMembership.objects.filter(
            group_id__in=group_ids,
            status=GroupMembership.Status.ACTIVE,
        ).values_list("user_id", flat=True)
    )


def social_calendar_description(event):
    parts = [event.description.strip()] if event.description.strip() else []
    if event.weather_dependent:
        parts.append("Weather permitting")
        if event.weather_note:
            parts.append(event.weather_note)
    if event.prizes:
        parts.append(f"Prizes / benefits: {event.prizes}")
    if event.rules:
        parts.append(f"Rules / notes: {event.rules}")
    return "\n".join(parts)


def upsert_social_calendar_event(event, user_id, *, active=True):
    defaults = {
        "title": event.title,
        "description": social_calendar_description(event),
        "start_at": event.start_at,
        "end_at": event.end_at,
        "timezone": event.timezone,
        "location_name": event.venue_name,
        "address_line1": event.address_line1,
        "address_line2": event.address_line2,
        "city": event.city,
        "state": event.state,
        "postal_code": event.postal_code,
        "country": event.country,
        "recurrence_rule": event.recurrence_rule,
        "source": PersonalCalendarEvent.Source.SYNC,
        "created_by_sync": True,
        "status": PersonalCalendarEvent.Status.ACTIVE if active and event.status != SocialEvent.Status.CANCELLED else PersonalCalendarEvent.Status.CANCELLED,
        "metadata": {
            "social_event_id": event.id,
            "social_event_version": event.version,
            "organizer_group_id": event.organizer_group_id,
            "weather_dependent": event.weather_dependent,
            "weather_note": event.weather_note,
            "social_event_status": event.status,
        },
    }
    existing = PersonalCalendarEvent.objects.filter(
        owner_id=user_id,
        source=PersonalCalendarEvent.Source.SYNC,
        metadata__social_event_id=event.id,
    ).first()
    if existing:
        for field, value in defaults.items():
            setattr(existing, field, value)
        existing.save()
        return existing
    return PersonalCalendarEvent.objects.create(owner_id=user_id, **defaults)


def ensure_group_event_responses(event, group_id):
    members = GroupMembership.objects.filter(
        group_id=group_id,
        status=GroupMembership.Status.ACTIVE,
    ).values_list("user_id", flat=True)
    for user_id in members:
        EventMemberResponse.objects.get_or_create(
            event=event,
            group_id=group_id,
            user_id=user_id,
            defaults={"response": EventMemberResponse.Response.PENDING},
        )


def sync_social_event_calendars(event):
    desired_user_ids = event_participant_user_ids(event)
    for user_id in desired_user_ids:
        response = EventMemberResponse.objects.filter(event=event, user_id=user_id).order_by("-updated_at").first()
        active = not response or response.response != EventMemberResponse.Response.NO
        upsert_social_calendar_event(event, user_id, active=active)
    existing = PersonalCalendarEvent.objects.filter(
        source=PersonalCalendarEvent.Source.SYNC,
        metadata__social_event_id=event.id,
    )
    existing.exclude(owner_id__in=desired_user_ids).update(status=PersonalCalendarEvent.Status.ARCHIVED)
    if event.status == SocialEvent.Status.CANCELLED:
        existing.update(status=PersonalCalendarEvent.Status.CANCELLED)


class PeopleViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = SocialUserSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = User.objects.exclude(pk=self.request.user.pk).order_by(
            "first_name", "last_name", "id"
        )
        search = str(self.request.query_params.get("search", "")).strip()
        if search:
            queryset = queryset.filter(
                Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(email__icontains=search)
            )
        else:
            queryset = queryset.none()
        return queryset[:50]


class ConnectionViewSet(viewsets.ModelViewSet):
    serializer_class = ConnectionSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        return Connection.objects.filter(
            Q(sender=self.request.user) | Q(recipient=self.request.user)
        ).select_related("sender", "recipient")

    def perform_create(self, serializer):
        recipient = serializer.validated_data["recipient"]
        if Connection.objects.filter(
            Q(sender=self.request.user, recipient=recipient)
            | Q(sender=recipient, recipient=self.request.user)
        ).exclude(status=Connection.Status.DECLINED).exists():
            raise serializers.ValidationError(
                "A connection request already exists between these users."
            )
        serializer.save(sender=self.request.user)

    def _respond(self, request, value):
        connection = self.get_object()
        if connection.recipient_id != request.user.id:
            return Response(
                {"detail": "Only the recipient can respond to this request."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if connection.status != Connection.Status.PENDING:
            return Response(
                {"detail": "This connection request has already been resolved."},
                status=status.HTTP_409_CONFLICT,
            )
        connection.status = value
        connection.responded_at = timezone.now()
        connection.save(update_fields=("status", "responded_at", "updated_at"))
        return Response(self.get_serializer(connection).data)

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        return self._respond(request, Connection.Status.ACCEPTED)

    @action(detail=True, methods=["post"])
    def decline(self, request, pk=None):
        return self._respond(request, Connection.Status.DECLINED)


class SocialGroupViewSet(viewsets.ModelViewSet):
    serializer_class = SocialGroupSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        member_ids = active_group_ids(self.request.user)
        return SocialGroup.objects.filter(
            Q(id__in=member_ids)
            | Q(created_by=self.request.user)
            | Q(visibility=SocialGroup.Visibility.PUBLIC),
            is_active=True,
        ).distinct().prefetch_related("memberships")

    def perform_create(self, serializer):
        parent = serializer.validated_data.get("parent")
        if parent and not can_manage_group(self.request.user, parent.id):
            raise serializers.ValidationError(
                "You must manage the parent group to create a child group."
            )
        with transaction.atomic():
            group = serializer.save(created_by=self.request.user)
            GroupMembership.objects.create(
                group=group,
                user=self.request.user,
                role=GroupMembership.Role.OWNER,
                status=GroupMembership.Status.ACTIVE,
                invited_by=self.request.user,
            )

    def perform_update(self, serializer):
        if not can_manage_group(self.request.user, self.get_object().id):
            raise serializers.ValidationError("You do not manage this group.")
        parent = serializer.validated_data.get("parent")
        if parent and not can_manage_group(self.request.user, parent.id):
            raise serializers.ValidationError(
                "You must manage the parent group to move this group there."
            )
        serializer.save()

    def perform_destroy(self, instance):
        if not can_manage_group(self.request.user, instance.id):
            raise serializers.ValidationError("You do not manage this group.")
        instance.is_active = False
        instance.save(update_fields=("is_active", "updated_at"))


class GroupMembershipViewSet(viewsets.ModelViewSet):
    serializer_class = GroupMembershipSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        return GroupMembership.objects.filter(
            Q(user=self.request.user)
            | Q(group_id__in=managed_group_ids(self.request.user))
        ).select_related("user", "group").distinct()

    def perform_create(self, serializer):
        group = serializer.validated_data["group"]
        if not can_manage_group(self.request.user, group.id):
            raise serializers.ValidationError("You do not manage this group.")
        serializer.save(
            invited_by=self.request.user,
            status=GroupMembership.Status.INVITED,
        )

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        membership = self.get_object()
        if membership.user_id != request.user.id:
            return Response(
                {"detail": "Only the invited member can accept."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if membership.status != GroupMembership.Status.INVITED:
            return Response(
                {"detail": "This membership invitation is no longer pending."},
                status=status.HTTP_409_CONFLICT,
            )
        membership.status = GroupMembership.Status.ACTIVE
        membership.save(update_fields=("status", "updated_at"))
        events = SocialEvent.objects.filter(
            Q(organizer_group=membership.group)
            | Q(group_invitations__target_group=membership.group, group_invitations__status=GroupEventInvitation.Status.ACCEPTED),
            status__in=(SocialEvent.Status.PUBLISHED, SocialEvent.Status.DRAFT),
        ).distinct()
        for event in events:
            ensure_group_event_responses(event, membership.group_id)
            sync_social_event_calendars(event)
        return Response(self.get_serializer(membership).data)

    @action(detail=True, methods=["post"])
    def decline(self, request, pk=None):
        membership = self.get_object()
        if membership.user_id != request.user.id:
            return Response(
                {"detail": "Only the invited member can decline."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if membership.status != GroupMembership.Status.INVITED:
            return Response(
                {"detail": "This membership invitation is no longer pending."},
                status=status.HTTP_409_CONFLICT,
            )
        membership.status = GroupMembership.Status.DECLINED
        membership.save(update_fields=("status", "updated_at"))
        return Response(self.get_serializer(membership).data)


class SocialEventViewSet(viewsets.ModelViewSet):
    serializer_class = SocialEventSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        group_ids = active_group_ids(self.request.user)
        return SocialEvent.objects.filter(
            Q(created_by=self.request.user)
            | Q(organizer_group_id__in=group_ids)
            | Q(group_invitations__target_group_id__in=group_ids)
        ).distinct().prefetch_related("group_invitations")

    def perform_create(self, serializer):
        group = serializer.validated_data.get("organizer_group")
        if group and not can_manage_group(self.request.user, group.id):
            raise serializers.ValidationError(
                "You do not manage the organizer group."
            )
        event = serializer.save(created_by=self.request.user)
        if group:
            ensure_group_event_responses(event, group.id)
        sync_social_event_calendars(event)

    def perform_update(self, serializer):
        event = self.get_object()
        allowed = (
            can_manage_group(self.request.user, event.organizer_group_id)
            if event.organizer_group_id
            else event.created_by_id == self.request.user.id
        )
        if not allowed:
            raise serializers.ValidationError("You do not manage this event.")
        event = serializer.save(version=event.version + 1)
        sync_social_event_calendars(event)

    def perform_destroy(self, instance):
        allowed = (
            can_manage_group(self.request.user, instance.organizer_group_id)
            if instance.organizer_group_id
            else instance.created_by_id == self.request.user.id
        )
        if not allowed:
            raise serializers.ValidationError("You do not manage this event.")
        instance.status = SocialEvent.Status.CANCELLED
        instance.version += 1
        instance.save(update_fields=("status", "version", "updated_at"))
        sync_social_event_calendars(instance)


class GroupEventInvitationViewSet(viewsets.ModelViewSet):
    serializer_class = GroupEventInvitationSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        group_ids = active_group_ids(self.request.user)
        return GroupEventInvitation.objects.filter(
            Q(invited_by=self.request.user) | Q(target_group_id__in=group_ids)
        ).select_related("event", "target_group").distinct()

    def perform_create(self, serializer):
        event = serializer.validated_data["event"]
        target_group = serializer.validated_data["target_group"]
        allowed = (
            can_manage_group(self.request.user, event.organizer_group_id)
            if event.organizer_group_id
            else event.created_by_id == self.request.user.id
        )
        if not allowed:
            raise serializers.ValidationError("You do not manage this event.")
        if event.organizer_group_id == target_group.id:
            raise serializers.ValidationError(
                "The organizer group is already part of this event."
            )
        serializer.save(invited_by=self.request.user)

    def _respond(self, request, value):
        invitation = self.get_object()
        if not can_manage_group(request.user, invitation.target_group_id):
            return Response(
                {"detail": "A group owner, director or manager must respond."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if invitation.status != GroupEventInvitation.Status.PENDING:
            return Response(
                {"detail": "This group invitation has already been resolved."},
                status=status.HTTP_409_CONFLICT,
            )
        invitation.status = value
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
        if value == GroupEventInvitation.Status.ACCEPTED:
            ensure_group_event_responses(invitation.event, invitation.target_group_id)
            sync_social_event_calendars(invitation.event)
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
            raise serializers.ValidationError(
                "You are not an active member of this group."
            )
        if not event_is_for_group(event, group.id):
            raise serializers.ValidationError(
                "This event has not been accepted by your group."
            )
        response = serializer.save(user=self.request.user, responded_at=timezone.now())
        upsert_social_calendar_event(event, self.request.user.id, active=response.response != EventMemberResponse.Response.NO)

    def perform_update(self, serializer):
        response = self.get_object()
        if response.user_id != self.request.user.id:
            raise serializers.ValidationError(
                "Only the member can change this response."
            )
        response = serializer.save(responded_at=timezone.now())
        upsert_social_calendar_event(response.event, response.user_id, active=response.response != EventMemberResponse.Response.NO)


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
        event = serializer.validated_data.get("event")
        if not can_manage_group(self.request.user, group.id):
            raise serializers.ValidationError("You do not manage this group.")
        if event and not event_is_for_group(event, group.id):
            raise serializers.ValidationError(
                "This event is not associated with the collection group."
            )
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        collection = self.get_object()
        if not can_manage_group(self.request.user, collection.group_id):
            raise serializers.ValidationError("You do not manage this collection.")
        new_group = serializer.validated_data.get("group", collection.group)
        new_event = serializer.validated_data.get("event", collection.event)
        if new_group.id != collection.group_id and not can_manage_group(
            self.request.user, new_group.id
        ):
            raise serializers.ValidationError("You do not manage the new group.")
        if new_event and not event_is_for_group(new_event, new_group.id):
            raise serializers.ValidationError(
                "This event is not associated with the collection group."
            )
        serializer.save()

    def perform_destroy(self, instance):
        if not can_manage_group(self.request.user, instance.group_id):
            raise serializers.ValidationError("You do not manage this collection.")
        instance.status = Collection.Status.CANCELLED
        instance.save(update_fields=("status", "updated_at"))


class CollectionShareViewSet(viewsets.ModelViewSet):
    serializer_class = CollectionShareSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return CollectionShare.objects.filter(
            Q(user=self.request.user)
            | Q(collection__group_id__in=managed_group_ids(self.request.user))
        ).select_related("user", "collection").distinct()

    def perform_create(self, serializer):
        collection = serializer.validated_data["collection"]
        if not can_manage_group(self.request.user, collection.group_id):
            raise serializers.ValidationError(
                "You do not manage this collection's group."
            )
        serializer.save()

    def perform_update(self, serializer):
        share = self.get_object()
        if not can_manage_group(self.request.user, share.collection.group_id):
            raise serializers.ValidationError(
                "Only group management can edit collection shares."
            )
        serializer.save()

    def perform_destroy(self, instance):
        if not can_manage_group(
            self.request.user, instance.collection.group_id
        ):
            raise serializers.ValidationError(
                "Only group management can remove collection shares."
            )
        instance.delete()
