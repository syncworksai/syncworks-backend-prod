from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from platform_social.models import CardPokerRoom, CardPokerSeat, GroupMembership, SocialGroup

User = get_user_model()


class CardPokerRoomsTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="poker-owner", email="poker-owner@example.com", password="x")
        self.member = User.objects.create_user(username="poker-member", email="poker-member@example.com", password="x")
        self.outsider = User.objects.create_user(username="poker-out", email="poker-out@example.com", password="x")
        self.group = SocialGroup.objects.create(name="Saturday League", kind="CLUB", created_by=self.owner)
        GroupMembership.objects.create(group=self.group, user=self.owner, role="OWNER", status="ACTIVE")
        GroupMembership.objects.create(group=self.group, user=self.member, role="MEMBER", status="ACTIVE")
        self.list_url = reverse("social-card-rooms")

    def create_room(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(self.list_url, {
            "group": self.group.id, "name": "Poker Night", "capacity": 4,
            "virtual_buy_in_cents": 2000,
        })
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(len(response.data["seats"]), 1)
        self.assertEqual(response.data["seats"][0]["user_id"], self.owner.id)
        return response.data["id"]

    def action(self, room, verb, payload=None):
        return self.client.post(reverse("social-card-room-action", kwargs={"room_id": room, "verb": verb}), payload or {})

    def test_group_members_join_their_own_seats_and_outsiders_are_blocked(self):
        room = self.create_room()
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get(self.list_url, {"group": self.group.id}).status_code, 403)
        self.assertEqual(self.action(room, "join").status_code, 404)
        self.client.force_authenticate(self.member)
        self.assertEqual(self.action(room, "join").status_code, 200)
        self.assertEqual(self.action(room, "join").status_code, 200)  # idempotent
        self.assertEqual(CardPokerSeat.objects.filter(room_id=room).count(), 2)

    def test_each_member_selects_virtual_buy_in_above_minimum(self):
        room = self.create_room()
        self.client.force_authenticate(self.member)
        low = self.action(room, "join", {"virtual_buy_in_cents": 1999})
        self.assertEqual(low.status_code, 400)
        self.assertFalse(CardPokerSeat.objects.filter(room_id=room, user=self.member).exists())
        joined = self.action(room, "join", {"virtual_buy_in_cents": 4000})
        self.assertEqual(joined.status_code, 200, joined.data)
        self.assertEqual(CardPokerSeat.objects.get(room_id=room, user=self.member).virtual_chips_cents, 4000)

    def test_room_creator_controls_start_and_dealer_rotation(self):
        room = self.create_room()
        self.client.force_authenticate(self.member)
        self.assertEqual(self.action(room, "start").status_code, 403)
        self.assertEqual(self.action(room, "join").status_code, 200)
        self.client.force_authenticate(self.owner)
        started = self.action(room, "start")
        self.assertEqual(started.status_code, 200, started.data)
        self.assertIn(started.data["dealer_position"], [0, 1])
        configured = self.action(room, "configure", {
            "game_code": "357", "game_selection": "DEALER",
            "ante_cents": 25, "pot_cap_cents": 5000,
        })
        self.assertEqual(configured.status_code, 200, configured.data)
        self.assertEqual(configured.data["state"], "READY")
        rotated = self.action(room, "next-dealer")
        self.assertEqual(rotated.status_code, 200, rotated.data)
        self.assertNotEqual(rotated.data["dealer_position"], started.data["dealer_position"])
        self.assertEqual(rotated.data["hand_number"], 2)

    def test_computer_is_a_single_host_controlled_seat(self):
        room = self.create_room()
        self.client.force_authenticate(self.member)
        self.assertEqual(self.action(room, "add-computer").status_code, 403)
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.action(room, "add-computer").status_code, 200)
        self.assertEqual(self.action(room, "add-computer").status_code, 409)
        self.assertEqual(CardPokerSeat.objects.filter(room_id=room, is_computer=True).count(), 1)

    def test_member_can_edit_only_own_nickname(self):
        room = self.create_room()
        self.client.force_authenticate(self.member)
        self.assertEqual(self.action(room, "nickname", {"nickname": "Ace"}).status_code, 403)
        self.action(room, "join")
        changed = self.action(room, "nickname", {"nickname": "Ace"})
        self.assertEqual(changed.status_code, 200, changed.data)
        self.assertTrue(any(s["name"] == "Ace" for s in changed.data["seats"]))
        self.assertEqual(CardPokerSeat.objects.get(room_id=room, user=self.owner).nickname, "")

    def test_invalid_stakes_and_unapproved_users_cannot_create_room(self):
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.post(self.list_url, {"group": self.group.pk, "name": "Outside", "capacity": 6}).status_code, 403)
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.post(self.list_url, {"group": self.group.pk, "name": "Invalid", "capacity": 100}).status_code, 400)
        room = self.create_room()
        self.action(room, "add-computer")
        self.action(room, "start")
        invalid = self.action(room, "configure", {"game_code": "bozo", "ante_cents": -1})
        self.assertEqual(invalid.status_code, 400)
