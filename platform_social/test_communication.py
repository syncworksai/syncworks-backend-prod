from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .communication_models import SocialMessage
from .models import GroupEventInvitation, GroupMembership, SocialEvent, SocialGroup

User = get_user_model()


class SocialCommunicationTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="chat-owner", email="chat-owner@example.com", password="pass12345")
        self.manager = User.objects.create_user(username="chat-manager", email="chat-manager@example.com", password="pass12345")
        self.member = User.objects.create_user(username="chat-member", email="chat-member@example.com", password="pass12345")
        self.outsider = User.objects.create_user(username="chat-outsider", email="chat-outsider@example.com", password="pass12345")
        self.organizer = User.objects.create_user(username="chat-organizer", email="chat-organizer@example.com", password="pass12345")
        self.team = SocialGroup.objects.create(name="Chat Team", kind=SocialGroup.Kind.TEAM, created_by=self.owner)
        for user, role in ((self.owner, GroupMembership.Role.OWNER), (self.manager, GroupMembership.Role.MANAGER), (self.member, GroupMembership.Role.MEMBER)):
            GroupMembership.objects.create(group=self.team, user=user, role=role, status=GroupMembership.Status.ACTIVE, invited_by=self.owner)
        self.organization = SocialGroup.objects.create(name="Chat Organization", kind=SocialGroup.Kind.ORGANIZATION, created_by=self.organizer)
        GroupMembership.objects.create(group=self.organization, user=self.organizer, role=GroupMembership.Role.OWNER, status=GroupMembership.Status.ACTIVE, invited_by=self.organizer)
        self.event = SocialEvent.objects.create(organizer_group=self.organization, created_by=self.organizer, title="Shared Event", start_at=timezone.now() + timedelta(days=7), status=SocialEvent.Status.PUBLISHED)
        self.invitation = GroupEventInvitation.objects.create(event=self.event, target_group=self.team, invited_by=self.organizer)

    def auth(self, user):
        self.client.force_authenticate(user=user)

    def result_rows(self, response):
        return response.data.get("results", []) if isinstance(response.data, dict) else response.data

    def test_active_members_share_one_group_feed(self):
        self.auth(self.member)
        created = self.client.post(reverse("social-room-feed"), {"group": self.team.id, "kind": "CHAT", "body": "Practice moved to 7."}, format="json")
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.auth(self.owner)
        feed = self.client.get(reverse("social-room-feed"), {"group": self.team.id, "event": "none"})
        self.assertEqual(feed.status_code, status.HTTP_200_OK)
        rows = self.result_rows(feed)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["body"], "Practice moved to 7.")
        self.assertEqual(rows[0]["sender"], self.member.id)

    def test_outsider_cannot_read_or_post(self):
        SocialMessage.objects.create(group=self.team, sender=self.member, body="Team only")
        self.auth(self.outsider)
        feed = self.client.get(reverse("social-room-feed"), {"group": self.team.id})
        self.assertEqual(feed.status_code, status.HTTP_200_OK)
        self.assertEqual(len(self.result_rows(feed)), 0)
        created = self.client.post(reverse("social-room-feed"), {"group": self.team.id, "body": "Hello"}, format="json")
        self.assertEqual(created.status_code, status.HTTP_400_BAD_REQUEST)

    def test_only_management_can_post_announcements(self):
        self.auth(self.member)
        denied = self.client.post(reverse("social-room-feed"), {"group": self.team.id, "kind": "ANNOUNCEMENT", "body": "Official update"}, format="json")
        self.assertEqual(denied.status_code, status.HTTP_400_BAD_REQUEST)
        self.auth(self.manager)
        allowed = self.client.post(reverse("social-room-feed"), {"group": self.team.id, "kind": "ANNOUNCEMENT", "body": "Official update"}, format="json")
        self.assertEqual(allowed.status_code, status.HTTP_201_CREATED)

    def test_event_room_requires_group_acceptance(self):
        self.auth(self.member)
        denied = self.client.post(reverse("social-room-feed"), {"group": self.team.id, "event": self.event.id, "body": "Can everyone make it?"}, format="json")
        self.assertEqual(denied.status_code, status.HTTP_400_BAD_REQUEST)
        self.invitation.status = GroupEventInvitation.Status.ACCEPTED
        self.invitation.responded_by = self.manager
        self.invitation.responded_at = timezone.now()
        self.invitation.save(update_fields=("status", "responded_by", "responded_at", "updated_at"))
        self.auth(self.member)
        allowed = self.client.post(reverse("social-room-feed"), {"group": self.team.id, "event": self.event.id, "body": "Can everyone make it?"}, format="json")
        self.assertEqual(allowed.status_code, status.HTTP_201_CREATED)

    def test_sender_can_edit_own_message_only(self):
        self.auth(self.member)
        created = self.client.post(reverse("social-room-feed"), {"group": self.team.id, "body": "Meet at 6"}, format="json")
        item_url = reverse("social-room-feed-item", args=[created.data["id"]])
        updated = self.client.patch(item_url, {"body": "Meet at 6:30"}, format="json")
        self.assertEqual(updated.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(updated.data["edited_at"])
        self.auth(self.owner)
        denied = self.client.patch(item_url, {"body": "Changed by owner"}, format="json")
        self.assertEqual(denied.status_code, status.HTTP_400_BAD_REQUEST)
