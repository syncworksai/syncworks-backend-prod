from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from personal_calendar.models import PersonalCalendarEvent

from .models import (
    Collection,
    EventMemberResponse,
    GroupEventInvitation,
    GroupMembership,
    SocialEvent,
    SocialGroup,
)

User = get_user_model()


class SocialApiPermissionTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="social-owner", email="owner@example.com", password="pass12345")
        self.manager = User.objects.create_user(username="social-manager", email="manager@example.com", password="pass12345")
        self.member = User.objects.create_user(username="social-member", email="member@example.com", password="pass12345")
        self.organizer = User.objects.create_user(username="social-organizer", email="organizer@example.com", password="pass12345")

        self.team = SocialGroup.objects.create(name="Test Team", kind=SocialGroup.Kind.TEAM, created_by=self.owner)
        GroupMembership.objects.create(group=self.team, user=self.owner, role=GroupMembership.Role.OWNER, status=GroupMembership.Status.ACTIVE, invited_by=self.owner)
        GroupMembership.objects.create(group=self.team, user=self.manager, role=GroupMembership.Role.MANAGER, status=GroupMembership.Status.ACTIVE, invited_by=self.owner)
        GroupMembership.objects.create(group=self.team, user=self.member, role=GroupMembership.Role.MEMBER, status=GroupMembership.Status.ACTIVE, invited_by=self.owner)

        self.organization = SocialGroup.objects.create(name="Test Organization", kind=SocialGroup.Kind.ORGANIZATION, created_by=self.organizer)
        GroupMembership.objects.create(group=self.organization, user=self.organizer, role=GroupMembership.Role.OWNER, status=GroupMembership.Status.ACTIVE, invited_by=self.organizer)
        self.event = SocialEvent.objects.create(
            organizer_group=self.organization,
            created_by=self.organizer,
            title="Test Invitational",
            start_at=timezone.now() + timedelta(days=10),
            venue_name="Original Park",
            address_line1="100 First Ave",
            city="Montgomery",
            state="AL",
            status=SocialEvent.Status.PUBLISHED,
        )
        self.invitation = GroupEventInvitation.objects.create(event=self.event, target_group=self.team, invited_by=self.organizer)
        self.collection = Collection.objects.create(group=self.team, created_by=self.owner, title="Entry Fee", total_amount_cents=40000, status=Collection.Status.OPEN)

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def social_calendar_rows(self, event=None):
        event = event or self.event
        return PersonalCalendarEvent.objects.filter(
            source=PersonalCalendarEvent.Source.SYNC,
            external_calendar_id="syncworks-social",
            external_event_id=f"social:{event.id}",
        )

    def test_plain_member_cannot_patch_group_event_invitation(self):
        self.authenticate(self.member)
        url = reverse("social-event-invitations-detail", args=[self.invitation.pk])
        response = self.client.patch(url, {"status": "ACCEPTED"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.invitation.refresh_from_db()
        self.assertEqual(self.invitation.status, GroupEventInvitation.Status.PENDING)

    def test_manager_can_accept_group_event_invitation(self):
        self.authenticate(self.manager)
        url = reverse("social-event-invitations-accept", args=[self.invitation.pk])
        response = self.client.post(url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.invitation.refresh_from_db()
        self.assertEqual(self.invitation.status, GroupEventInvitation.Status.ACCEPTED)
        self.assertEqual(self.invitation.responded_by_id, self.manager.id)

    def test_accepting_group_event_seeds_pending_rsvp_for_every_active_member(self):
        self.authenticate(self.manager)
        response = self.client.post(reverse("social-event-invitations-accept", args=[self.invitation.pk]), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = EventMemberResponse.objects.filter(event=self.event, group=self.team)
        self.assertEqual(rows.count(), 3)
        self.assertEqual(set(rows.values_list("response", flat=True)), {EventMemberResponse.Response.PENDING})

    def test_accepting_group_event_adds_one_calendar_entry_per_active_member(self):
        self.authenticate(self.manager)
        response = self.client.post(reverse("social-event-invitations-accept", args=[self.invitation.pk]), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        rows = self.social_calendar_rows()
        # Organizer already receives the organizer event; accepting the team adds its 3 active members.
        self.assertEqual(rows.count(), 4)
        self.assertEqual(set(rows.values_list("owner_id", flat=True)), {self.organizer.id, self.owner.id, self.manager.id, self.member.id})
        self.assertTrue(all(row.created_by_sync for row in rows))

    def test_social_event_edit_updates_linked_calendars_without_duplicates(self):
        self.authenticate(self.manager)
        self.client.post(reverse("social-event-invitations-accept", args=[self.invitation.pk]), {}, format="json")
        original_count = self.social_calendar_rows().count()
        new_start = self.event.start_at + timedelta(hours=2)

        self.authenticate(self.organizer)
        response = self.client.patch(
            reverse("social-events-detail", args=[self.event.pk]),
            {
                "start_at": new_start.isoformat(),
                "venue_name": "Updated Park",
                "address_line1": "200 Second Ave",
                "city": "Birmingham",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.social_calendar_rows().count(), original_count)
        for row in self.social_calendar_rows():
            self.assertEqual(row.title, "Test Invitational")
            self.assertEqual(row.start_at, new_start)
            self.assertEqual(row.location_name, "Updated Park")
            self.assertEqual(row.address_line1, "200 Second Ave")
            self.assertEqual(row.city, "Birmingham")
            self.assertEqual(row.metadata.get("social_event_version"), 2)

    def test_social_event_cancellation_cancels_all_linked_calendar_entries(self):
        self.authenticate(self.manager)
        self.client.post(reverse("social-event-invitations-accept", args=[self.invitation.pk]), {}, format="json")
        original_count = self.social_calendar_rows().count()

        self.authenticate(self.organizer)
        response = self.client.delete(reverse("social-events-detail", args=[self.event.pk]))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(self.social_calendar_rows().count(), original_count)
        self.assertFalse(self.social_calendar_rows().exclude(status=PersonalCalendarEvent.Status.CANCELLED).exists())
        self.assertTrue(all(row.audit_entries.filter(action="CANCELLED").exists() for row in self.social_calendar_rows()))

    def test_plain_member_cannot_edit_collection(self):
        self.authenticate(self.member)
        url = reverse("social-collections-detail", args=[self.collection.pk])
        response = self.client.patch(url, {"total_amount_cents": 1}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.collection.refresh_from_db()
        self.assertEqual(self.collection.total_amount_cents, 40000)

    def test_member_cannot_rsvp_until_group_accepts_event(self):
        self.authenticate(self.member)
        list_url = reverse("social-event-responses-list")
        response = self.client.post(list_url, {"event": self.event.id, "group": self.team.id, "response": "YES"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.authenticate(self.manager)
        accept_url = reverse("social-event-invitations-accept", args=[self.invitation.pk])
        response = self.client.post(accept_url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        seeded = EventMemberResponse.objects.get(event=self.event, group=self.team, user=self.member)
        self.authenticate(self.member)
        response = self.client.patch(reverse("social-event-responses-detail", args=[seeded.pk]), {"response": "YES"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["response"], "YES")

    def test_new_active_member_gets_pending_rsvp_and_calendar_for_already_accepted_event(self):
        self.authenticate(self.manager)
        response = self.client.post(reverse("social-event-invitations-accept", args=[self.invitation.pk]), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        late_member = User.objects.create_user(username="late-member", email="late@example.com", password="pass12345")
        membership = GroupMembership.objects.create(
            group=self.team,
            user=late_member,
            role=GroupMembership.Role.MEMBER,
            status=GroupMembership.Status.INVITED,
            invited_by=self.manager,
        )
        membership.status = GroupMembership.Status.ACTIVE
        membership.save(update_fields=("status", "updated_at"))

        self.assertTrue(EventMemberResponse.objects.filter(event=self.event, group=self.team, user=late_member, response=EventMemberResponse.Response.PENDING).exists())
        self.assertTrue(self.social_calendar_rows().filter(owner=late_member).exists())

    def test_member_cannot_create_child_group_under_group_they_do_not_manage(self):
        self.authenticate(self.member)
        url = reverse("social-groups-list")
        response = self.client.post(url, {"name": "Unauthorized Child", "kind": "TEAM", "visibility": "PRIVATE", "parent": self.organization.id}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_manager_can_update_collection_amount(self):
        self.authenticate(self.manager)
        url = reverse("social-collections-detail", args=[self.collection.pk])
        response = self.client.patch(url, {"total_amount_cents": 45000}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.collection.refresh_from_db()
        self.assertEqual(self.collection.total_amount_cents, 45000)
