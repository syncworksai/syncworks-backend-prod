from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from personal_calendar.models import PersonalCalendarEvent
from .models import EventMemberResponse, GroupEventInvitation, GroupMembership, SocialEvent, SocialGroup

User = get_user_model()


class SocialCalendarPropagationTests(APITestCase):
    def setUp(self):
        self.organizer = User.objects.create_user(username="social-cal-org", email="org-cal@example.com", password="pass12345")
        self.owner = User.objects.create_user(username="social-cal-owner", email="owner-cal@example.com", password="pass12345")
        self.manager = User.objects.create_user(username="social-cal-manager", email="manager-cal@example.com", password="pass12345")
        self.member = User.objects.create_user(username="social-cal-member", email="member-cal@example.com", password="pass12345")

        self.organization = SocialGroup.objects.create(name="Calendar League", kind=SocialGroup.Kind.ORGANIZATION, created_by=self.organizer)
        GroupMembership.objects.create(group=self.organization, user=self.organizer, role=GroupMembership.Role.OWNER, status=GroupMembership.Status.ACTIVE, invited_by=self.organizer)
        self.team = SocialGroup.objects.create(name="Calendar Team", kind=SocialGroup.Kind.TEAM, created_by=self.owner)
        GroupMembership.objects.create(group=self.team, user=self.owner, role=GroupMembership.Role.OWNER, status=GroupMembership.Status.ACTIVE, invited_by=self.owner)
        GroupMembership.objects.create(group=self.team, user=self.manager, role=GroupMembership.Role.MANAGER, status=GroupMembership.Status.ACTIVE, invited_by=self.owner)
        GroupMembership.objects.create(group=self.team, user=self.member, role=GroupMembership.Role.MEMBER, status=GroupMembership.Status.ACTIVE, invited_by=self.owner)

        self.event = SocialEvent.objects.create(
            organizer_group=self.organization,
            created_by=self.organizer,
            title="Calendar Invitational",
            start_at=timezone.now() + timedelta(days=10),
            venue_name="Original Park",
            address_line1="100 First Ave",
            city="Montgomery",
            state="AL",
            status=SocialEvent.Status.PUBLISHED,
        )
        self.invitation = GroupEventInvitation.objects.create(event=self.event, target_group=self.team, invited_by=self.organizer)

    def social_rows(self):
        return PersonalCalendarEvent.objects.filter(
            source=PersonalCalendarEvent.Source.SYNC,
            external_calendar_id="syncworks-social",
            external_event_id=f"social:{self.event.id}",
        )

    def accept(self):
        self.client.force_authenticate(user=self.manager)
        response = self.client.post(reverse("social-event-invitations-accept", args=[self.invitation.pk]), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_acceptance_seeds_rsvps_and_unique_calendar_rows(self):
        self.accept()
        responses = EventMemberResponse.objects.filter(event=self.event, group=self.team)
        self.assertEqual(responses.count(), 3)
        self.assertEqual(set(responses.values_list("response", flat=True)), {EventMemberResponse.Response.PENDING})
        rows = self.social_rows()
        self.assertEqual(rows.count(), 4)
        self.assertEqual(set(rows.values_list("owner_id", flat=True)), {self.organizer.id, self.owner.id, self.manager.id, self.member.id})

    def test_event_edit_updates_existing_calendar_rows(self):
        self.accept()
        original_count = self.social_rows().count()
        new_start = self.event.start_at + timedelta(hours=2)
        self.client.force_authenticate(user=self.organizer)
        response = self.client.patch(
            reverse("social-events-detail", args=[self.event.pk]),
            {"start_at": new_start.isoformat(), "venue_name": "Updated Park", "address_line1": "200 Second Ave", "city": "Birmingham"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.social_rows().count(), original_count)
        for row in self.social_rows():
            self.assertEqual(row.start_at, new_start)
            self.assertEqual(row.location_name, "Updated Park")
            self.assertEqual(row.city, "Birmingham")

    def test_cancellation_cancels_linked_calendar_rows(self):
        self.accept()
        original_count = self.social_rows().count()
        self.client.force_authenticate(user=self.organizer)
        response = self.client.delete(reverse("social-events-detail", args=[self.event.pk]))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(self.social_rows().count(), original_count)
        self.assertFalse(self.social_rows().exclude(status=PersonalCalendarEvent.Status.CANCELLED).exists())

    def test_late_active_member_inherits_rsvp_and_calendar(self):
        self.accept()
        late = User.objects.create_user(username="social-cal-late", email="late-cal@example.com", password="pass12345")
        membership = GroupMembership.objects.create(group=self.team, user=late, role=GroupMembership.Role.MEMBER, status=GroupMembership.Status.INVITED, invited_by=self.manager)
        membership.status = GroupMembership.Status.ACTIVE
        membership.save(update_fields=("status", "updated_at"))
        self.assertTrue(EventMemberResponse.objects.filter(event=self.event, group=self.team, user=late, response=EventMemberResponse.Response.PENDING).exists())
        self.assertTrue(self.social_rows().filter(owner=late).exists())
