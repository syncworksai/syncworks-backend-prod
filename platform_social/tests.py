from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import (
    Collection,
    GroupEventInvitation,
    GroupMembership,
    SocialEvent,
    SocialGroup,
)

User = get_user_model()


class SocialApiPermissionTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="social-owner",
            email="owner@example.com",
            password="pass12345",
        )
        self.manager = User.objects.create_user(
            username="social-manager",
            email="manager@example.com",
            password="pass12345",
        )
        self.member = User.objects.create_user(
            username="social-member",
            email="member@example.com",
            password="pass12345",
        )
        self.organizer = User.objects.create_user(
            username="social-organizer",
            email="organizer@example.com",
            password="pass12345",
        )

        self.team = SocialGroup.objects.create(
            name="Test Team",
            kind=SocialGroup.Kind.TEAM,
            created_by=self.owner,
        )
        GroupMembership.objects.create(
            group=self.team,
            user=self.owner,
            role=GroupMembership.Role.OWNER,
            status=GroupMembership.Status.ACTIVE,
            invited_by=self.owner,
        )
        GroupMembership.objects.create(
            group=self.team,
            user=self.manager,
            role=GroupMembership.Role.MANAGER,
            status=GroupMembership.Status.ACTIVE,
            invited_by=self.owner,
        )
        GroupMembership.objects.create(
            group=self.team,
            user=self.member,
            role=GroupMembership.Role.MEMBER,
            status=GroupMembership.Status.ACTIVE,
            invited_by=self.owner,
        )

        self.organization = SocialGroup.objects.create(
            name="Test Organization",
            kind=SocialGroup.Kind.ORGANIZATION,
            created_by=self.organizer,
        )
        GroupMembership.objects.create(
            group=self.organization,
            user=self.organizer,
            role=GroupMembership.Role.OWNER,
            status=GroupMembership.Status.ACTIVE,
            invited_by=self.organizer,
        )
        self.event = SocialEvent.objects.create(
            organizer_group=self.organization,
            created_by=self.organizer,
            title="Test Invitational",
            start_at=timezone.now() + timedelta(days=10),
            status=SocialEvent.Status.PUBLISHED,
        )
        self.invitation = GroupEventInvitation.objects.create(
            event=self.event,
            target_group=self.team,
            invited_by=self.organizer,
        )
        self.collection = Collection.objects.create(
            group=self.team,
            created_by=self.owner,
            title="Entry Fee",
            total_amount_cents=40000,
            status=Collection.Status.OPEN,
        )

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def test_plain_member_cannot_patch_group_event_invitation(self):
        self.authenticate(self.member)
        url = reverse(
            "social-event-invitations-detail",
            args=[self.invitation.pk],
        )
        response = self.client.patch(url, {"status": "ACCEPTED"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.invitation.refresh_from_db()
        self.assertEqual(
            self.invitation.status,
            GroupEventInvitation.Status.PENDING,
        )

    def test_manager_can_accept_group_event_invitation(self):
        self.authenticate(self.manager)
        url = reverse(
            "social-event-invitations-accept",
            args=[self.invitation.pk],
        )
        response = self.client.post(url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.invitation.refresh_from_db()
        self.assertEqual(
            self.invitation.status,
            GroupEventInvitation.Status.ACCEPTED,
        )
        self.assertEqual(self.invitation.responded_by_id, self.manager.id)

    def test_plain_member_cannot_edit_collection(self):
        self.authenticate(self.member)
        url = reverse("social-collections-detail", args=[self.collection.pk])
        response = self.client.patch(
            url,
            {"total_amount_cents": 1},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.collection.refresh_from_db()
        self.assertEqual(self.collection.total_amount_cents, 40000)

    def test_member_cannot_rsvp_until_group_accepts_event(self):
        self.authenticate(self.member)
        url = reverse("social-event-responses-list")
        response = self.client.post(
            url,
            {
                "event": self.event.id,
                "group": self.team.id,
                "response": "YES",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.invitation.status = GroupEventInvitation.Status.ACCEPTED
        self.invitation.responded_by = self.manager
        self.invitation.responded_at = timezone.now()
        self.invitation.save(
            update_fields=("status", "responded_by", "responded_at", "updated_at")
        )

        response = self.client.post(
            url,
            {
                "event": self.event.id,
                "group": self.team.id,
                "response": "YES",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["response"], "YES")

    def test_member_cannot_create_child_group_under_group_they_do_not_manage(self):
        self.authenticate(self.member)
        url = reverse("social-groups-list")
        response = self.client.post(
            url,
            {
                "name": "Unauthorized Child",
                "kind": "TEAM",
                "visibility": "PRIVATE",
                "parent": self.organization.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_manager_can_update_collection_amount(self):
        self.authenticate(self.manager)
        url = reverse("social-collections-detail", args=[self.collection.pk])
        response = self.client.patch(
            url,
            {"total_amount_cents": 45000},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.collection.refresh_from_db()
        self.assertEqual(self.collection.total_amount_cents, 45000)
