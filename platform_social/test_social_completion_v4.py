from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from .models import GroupMembership, SocialGroup


User = get_user_model()


class GroupFollowCategoryTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner@example.com", email="owner@example.com", password="test-pass-123")
        self.fan = User.objects.create_user(username="fan@example.com", email="fan@example.com", password="test-pass-123")
        self.group = SocialGroup.objects.create(
            name="Test Softball",
            kind=SocialGroup.Kind.TEAM,
            category=SocialGroup.Category.SPORTS,
            visibility=SocialGroup.Visibility.PUBLIC,
            created_by=self.owner,
        )
        GroupMembership.objects.create(
            group=self.group,
            user=self.owner,
            role=GroupMembership.Role.OWNER,
            status=GroupMembership.Status.ACTIVE,
            invited_by=self.owner,
        )

    def test_public_group_follow_cycle(self):
        self.client.force_authenticate(self.fan)
        response = self.client.post(f"/api/v1/social/groups/{self.group.id}/follow/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["is_following"])
        self.assertEqual(response.data["follower_count"], 1)
        response = self.client.post(f"/api/v1/social/groups/{self.group.id}/unfollow/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["is_following"])

    def test_user_payment_profile(self):
        self.client.force_authenticate(self.fan)
        response = self.client.patch(
            "/api/v1/social/groups/payment-profile/",
            {"cash_app_url": "https://cash.app/example", "venmo_label": "example"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["venmo_label"], "example")
