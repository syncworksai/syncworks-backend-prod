from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from platform_social.models import (
    Collection,
    CollectionPayment,
    CollectionShare,
    GroupMembership,
    SocialGroup,
)

User = get_user_model()


class SocialInviteAndCollectTests(APITestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username="manager", email="manager@example.com", password="pass12345")
        self.member = User.objects.create_user(username="member", email="member@example.com", password="pass12345")
        self.group = SocialGroup.objects.create(
            name="Bed Springs Baptist",
            kind=SocialGroup.Kind.TEAM,
            visibility=SocialGroup.Visibility.PRIVATE,
            created_by=self.manager,
        )
        GroupMembership.objects.create(
            group=self.group,
            user=self.manager,
            role=GroupMembership.Role.OWNER,
            status=GroupMembership.Status.ACTIVE,
            invited_by=self.manager,
        )

    def test_share_link_creates_manager_approved_join_request(self):
        self.client.force_authenticate(self.manager)
        created = self.client.post(
            reverse("social-groups-invite-link", args=[self.group.id]),
            {"role": "MEMBER"},
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_200_OK)
        token = created.data["token"]

        self.client.force_authenticate(user=None)
        preview = self.client.get(reverse("social-group-invite-links-preview"), {"token": token})
        self.assertEqual(preview.status_code, status.HTTP_200_OK)
        self.assertEqual(preview.data["group"]["name"], "Bed Springs Baptist")

        self.client.force_authenticate(self.member)
        requested = self.client.post(
            reverse("social-group-invite-links-request-join"),
            {"token": token},
            format="json",
        )
        self.assertEqual(requested.status_code, status.HTTP_201_CREATED)
        membership = GroupMembership.objects.get(group=self.group, user=self.member)
        self.assertEqual(membership.status, GroupMembership.Status.REQUESTED)

        self.client.force_authenticate(self.manager)
        approved = self.client.post(reverse("social-memberships-accept", args=[membership.id]))
        self.assertEqual(approved.status_code, status.HTTP_200_OK)
        membership.refresh_from_db()
        self.assertEqual(membership.status, GroupMembership.Status.ACTIVE)

    def test_collect_payment_tracks_fixed_one_percent_platform_fee(self):
        collection = Collection.objects.create(
            group=self.group,
            created_by=self.manager,
            title="League fee",
            total_amount_cents=5000,
            status=Collection.Status.OPEN,
            platform_fee_bps=999,
        )
        collection.refresh_from_db()
        self.assertEqual(collection.platform_fee_bps, 100)

        share = CollectionShare.objects.create(
            collection=collection,
            user=self.member,
            amount_due_cents=5000,
        )
        self.client.force_authenticate(self.manager)
        paid = self.client.post(
            reverse("social-collection-shares-record-payment", args=[share.id]),
            {"amount_cents": 5000, "method": "VENMO", "external_reference": "manual-confirmation"},
            format="json",
        )
        self.assertEqual(paid.status_code, status.HTTP_201_CREATED)
        payment = CollectionPayment.objects.get(share=share)
        self.assertEqual(payment.platform_fee_bps, 100)
        self.assertEqual(payment.platform_fee_cents, 50)
        self.assertEqual(payment.fee_status, CollectionPayment.FeeStatus.PENDING)
        share.refresh_from_db()
        self.assertEqual(share.status, CollectionShare.Status.PAID)
        self.assertEqual(share.amount_paid_cents, 5000)
