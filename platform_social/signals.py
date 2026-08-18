from django.db.models.signals import post_save
from django.dispatch import receiver

from personal_calendar.models import PersonalCalendarEvent, PersonalCalendarEventAudit

from .models import EventMemberResponse, GroupEventInvitation, GroupMembership, SocialEvent

SOCIAL_CALENDAR_ID = "syncworks-social"


def _calendar_external_event_id(event):
    return f"social:{event.id}"


def _calendar_description(event):
    details = [str(event.description or "").strip()]
    if event.entry_amount_cents:
        details.append(f"Entry / cost: ${event.entry_amount_cents / 100:,.2f}")
    if event.prizes:
        details.append(f"Prizes: {event.prizes}")
    if event.rules:
        details.append(f"Rules: {event.rules}")
    return "\n\n".join(value for value in details if value)


def _calendar_defaults(event, existing=None):
    metadata = dict(getattr(existing, "metadata", {}) or {})
    metadata.update({
        "social_event_id": event.id,
        "social_event_version": event.version,
        "social_status": event.status,
        "organizer_group_id": event.organizer_group_id,
        "flyer_url": event.flyer_url or "",
        "payment_due_at": event.payment_due_at.isoformat() if event.payment_due_at else None,
        "entry_amount_cents": event.entry_amount_cents,
    })
    return {
        "title": event.title,
        "description": _calendar_description(event),
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
        "created_by_sync": True,
        "status": PersonalCalendarEvent.Status.CANCELLED if event.status == SocialEvent.Status.CANCELLED else PersonalCalendarEvent.Status.ACTIVE,
        "metadata": metadata,
    }


def sync_event_to_user_calendar(event, user_id):
    lookup = {
        "owner_id": user_id,
        "source": PersonalCalendarEvent.Source.SYNC,
        "external_calendar_id": SOCIAL_CALENDAR_ID,
        "external_event_id": _calendar_external_event_id(event),
    }
    existing = PersonalCalendarEvent.objects.filter(**lookup).first()
    defaults = _calendar_defaults(event, existing=existing)
    if existing is None:
        calendar_event = PersonalCalendarEvent.objects.create(**lookup, **defaults)
        PersonalCalendarEventAudit.objects.create(
            event=calendar_event,
            actor=event.created_by,
            action=PersonalCalendarEventAudit.Action.CREATED,
            changes={"source": "SOCIAL", "social_event_id": event.id, "social_event_version": event.version},
        )
        return calendar_event

    changed_fields = []
    for field, value in defaults.items():
        if getattr(existing, field) != value:
            setattr(existing, field, value)
            changed_fields.append(field)
    if changed_fields:
        existing.save(update_fields=tuple(changed_fields + ["updated_at"]))
        action = PersonalCalendarEventAudit.Action.CANCELLED if existing.status == PersonalCalendarEvent.Status.CANCELLED else PersonalCalendarEventAudit.Action.UPDATED
        PersonalCalendarEventAudit.objects.create(
            event=existing,
            actor=event.created_by,
            action=action,
            changes={"source": "SOCIAL", "social_event_id": event.id, "social_event_version": event.version, "fields": changed_fields},
        )
    return existing


def _active_member_user_ids(group_id):
    return GroupMembership.objects.filter(group_id=group_id, status=GroupMembership.Status.ACTIVE).values_list("user_id", flat=True)


def calendar_recipient_user_ids(event):
    user_ids = {event.created_by_id}
    if event.organizer_group_id:
        user_ids.update(_active_member_user_ids(event.organizer_group_id))
    accepted_group_ids = GroupEventInvitation.objects.filter(event=event, status=GroupEventInvitation.Status.ACCEPTED).values_list("target_group_id", flat=True)
    for group_id in accepted_group_ids:
        user_ids.update(_active_member_user_ids(group_id))
    return user_ids


def sync_event_calendars(event):
    existing_user_ids = PersonalCalendarEvent.objects.filter(
        source=PersonalCalendarEvent.Source.SYNC,
        external_calendar_id=SOCIAL_CALENDAR_ID,
        external_event_id=_calendar_external_event_id(event),
    ).values_list("owner_id", flat=True)
    user_ids = set(existing_user_ids)
    if event.status != SocialEvent.Status.CANCELLED:
        user_ids.update(calendar_recipient_user_ids(event))
    for user_id in user_ids:
        sync_event_to_user_calendar(event, user_id)


def seed_pending_responses(event, group):
    if not event or not group:
        return
    active_user_ids = list(_active_member_user_ids(group.id))
    existing_user_ids = set(EventMemberResponse.objects.filter(event=event, group=group, user_id__in=active_user_ids).values_list("user_id", flat=True))
    EventMemberResponse.objects.bulk_create(
        [EventMemberResponse(event=event, group=group, user_id=user_id, response=EventMemberResponse.Response.PENDING) for user_id in active_user_ids if user_id not in existing_user_ids],
        ignore_conflicts=True,
    )


@receiver(post_save, sender=SocialEvent)
def sync_social_event_changes_to_calendars(sender, instance, **kwargs):
    sync_event_calendars(instance)


@receiver(post_save, sender=GroupEventInvitation)
def seed_responses_when_group_accepts_event(sender, instance, **kwargs):
    if instance.status == GroupEventInvitation.Status.ACCEPTED:
        seed_pending_responses(instance.event, instance.target_group)
        for user_id in _active_member_user_ids(instance.target_group_id):
            sync_event_to_user_calendar(instance.event, user_id)


@receiver(post_save, sender=GroupMembership)
def seed_responses_when_member_becomes_active(sender, instance, **kwargs):
    if instance.status != GroupMembership.Status.ACTIVE:
        return
    accepted_event_ids = GroupEventInvitation.objects.filter(target_group=instance.group, status=GroupEventInvitation.Status.ACCEPTED).values_list("event_id", flat=True)
    organizer_event_ids = SocialEvent.objects.filter(organizer_group=instance.group).values_list("id", flat=True)
    event_ids = set(accepted_event_ids) | set(organizer_event_ids)
    for event in SocialEvent.objects.filter(id__in=event_ids):
        EventMemberResponse.objects.get_or_create(event=event, group=instance.group, user=instance.user, defaults={"response": EventMemberResponse.Response.PENDING})
        sync_event_to_user_calendar(event, instance.user_id)
