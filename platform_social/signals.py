from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import (
    EventMemberResponse,
    GroupEventInvitation,
    GroupMembership,
    SocialEvent,
)


def seed_pending_responses(event, group):
    """Ensure every active group member has an RSVP row for an accepted event."""
    if not event or not group:
        return

    active_user_ids = GroupMembership.objects.filter(
        group=group,
        status=GroupMembership.Status.ACTIVE,
    ).values_list("user_id", flat=True)

    existing_user_ids = set(
        EventMemberResponse.objects.filter(
            event=event,
            group=group,
            user_id__in=active_user_ids,
        ).values_list("user_id", flat=True)
    )

    EventMemberResponse.objects.bulk_create(
        [
            EventMemberResponse(
                event=event,
                group=group,
                user_id=user_id,
                response=EventMemberResponse.Response.PENDING,
            )
            for user_id in active_user_ids
            if user_id not in existing_user_ids
        ],
        ignore_conflicts=True,
    )


@receiver(post_save, sender=GroupEventInvitation)
def seed_responses_when_group_accepts_event(sender, instance, **kwargs):
    if instance.status == GroupEventInvitation.Status.ACCEPTED:
        seed_pending_responses(instance.event, instance.target_group)


@receiver(post_save, sender=GroupMembership)
def seed_responses_when_member_becomes_active(sender, instance, **kwargs):
    if instance.status != GroupMembership.Status.ACTIVE:
        return

    accepted_event_ids = GroupEventInvitation.objects.filter(
        target_group=instance.group,
        status=GroupEventInvitation.Status.ACCEPTED,
    ).values_list("event_id", flat=True)

    organizer_event_ids = SocialEvent.objects.filter(
        organizer_group=instance.group,
    ).values_list("id", flat=True)

    event_ids = set(accepted_event_ids) | set(organizer_event_ids)
    for event in SocialEvent.objects.filter(id__in=event_ids):
        EventMemberResponse.objects.get_or_create(
            event=event,
            group=instance.group,
            user=instance.user,
            defaults={"response": EventMemberResponse.Response.PENDING},
        )
