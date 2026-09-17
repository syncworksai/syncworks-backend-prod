from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from platform_social.models import GroupMembership, SocialGroup

User = get_user_model()


class GroupMessageApiTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="chat-owner", email="owner-chat@example.com", password="x")
        self.member = User.objects.create_user(username="chat-member", email="member-chat@example.com", password="x")
        self.outsider = User.objects.create_user(username="chat-out", email="out-chat@example.com", password="x")
        self.group = SocialGroup.objects.create(name="Team Chat", kind=SocialGroup.Kind.TEAM, created_by=self.owner)
        for user, role in ((self.owner, GroupMembership.Role.OWNER), (self.member, GroupMembership.Role.MEMBER)):
            GroupMembership.objects.create(group=self.group, user=user, role=role, status=GroupMembership.Status.ACTIVE, invited_by=self.owner)

    def test_group_members_can_chat_and_outsiders_cannot_read(self):
        self.client.force_authenticate(self.member)
        created = self.client.post(reverse("social-group-messages-list"), {"group": self.group.id, "body": "Who is in Tuesday?"}, format="json")
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(created.data["author_detail"]["email"], self.member.email)

        self.client.force_authenticate(self.owner)
        rows = self.client.get(reverse("social-group-messages-list"), {"group": self.group.id})
        self.assertEqual(rows.status_code, status.HTTP_200_OK)
        payload = rows.data.get("results", rows.data) if isinstance(rows.data, dict) else rows.data
        self.assertEqual(len(payload), 1)

        self.client.force_authenticate(self.outsider)
        hidden = self.client.get(reverse("social-group-messages-list"), {"group": self.group.id})
        self.assertEqual(hidden.status_code, status.HTTP_200_OK)
        hidden_payload = hidden.data.get("results", hidden.data) if isinstance(hidden.data, dict) else hidden.data
        self.assertEqual(len(hidden_payload), 0)

    def test_manager_can_remove_group_message(self):
        self.client.force_authenticate(self.member)
        created = self.client.post(reverse("social-group-messages-list"), {"group": self.group.id, "body": "Old message"}, format="json")
        self.client.force_authenticate(self.owner)
        deleted = self.client.delete(reverse("social-group-messages-detail", args=[created.data["id"]]))
        self.assertEqual(deleted.status_code, status.HTTP_204_NO_CONTENT)
