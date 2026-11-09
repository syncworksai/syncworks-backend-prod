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

    def test_host_can_fill_five_virtual_player_seats_without_exceeding_capacity(self):
        room = self.create_room()
        self.client.force_authenticate(self.member)
        self.assertEqual(self.action(room, "add-computer").status_code, 403)
        self.client.force_authenticate(self.owner)
        for i in range(5):
            response = self.action(room, "add-computer")
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(len(response.data["seats"]), i + 2)
            self.assertEqual(
                sorted(s["name"] for s in response.data["seats"] if s["is_computer"]),
                [f"Virtual Player {n}" for n in range(1, i + 2)],
            )
            self.assertEqual(
                sum(s["virtual_chips_cents"] for s in response.data["seats"]),
                (i + 2) * 2000,
            )
        self.assertEqual(self.action(room, "add-computer").status_code, 409)
        self.assertEqual(CardPokerSeat.objects.filter(room_id=room, is_computer=True).count(), 5)
        self.assertEqual(CardPokerSeat.objects.filter(room_id=room).count(), 6)
        # All six positions are unique and the full virtual table can select a dealer.
        self.assertEqual(len(set(CardPokerSeat.objects.filter(room_id=room).values_list("position", flat=True))), 6)
        started = self.action(room, "start")
        self.assertEqual(started.status_code, 200, started.data)
        self.assertIn(started.data["dealer_position"], range(6))

    def test_virtual_players_share_capacity_with_real_members(self):
        room = self.create_room()
        self.client.force_authenticate(self.member)
        self.assertEqual(self.action(room, "join").status_code, 200)
        self.client.force_authenticate(self.owner)
        for i in range(4):
            self.assertEqual(self.action(room, "add-computer").status_code, 200)
        self.assertEqual(self.action(room, "add-computer").status_code, 409)
        self.assertEqual(CardPokerSeat.objects.filter(room_id=room, is_computer=True).count(), 4)

    def test_computer_seat_does_not_fail_when_user_is_null(self):
        room = self.create_room()
        self.client.force_authenticate(self.owner)
        added = self.action(room, "add-computer")
        self.assertEqual(added.status_code, 200, added.data)
        self.assertTrue(any(seat["is_computer"] and seat["user_id"] is None for seat in added.data["seats"]))
        # This action used to raise PostgreSQL NotSupportedError because a nullable
        # user was joined while locking the seats with SELECT FOR UPDATE.
        started = self.action(room, "start")
        self.assertEqual(started.status_code, 200, started.data)
        self.assertEqual(started.data["state"], "DEALER")

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

    def test_admissions_can_close_and_reopen_without_ending_the_room(self):
        room=self.create_room()
        self.assertFalse(self.action(room,"admission",{"open":False}).data["admission_open"])\n        self.client.force_authenticate(self.member)\n        self.assertEqual(self.action(room,"join").status_code,409)\n        self.assertEqual(self.action(room,"admission",{"open":True}).status_code,403)\n        self.client.force_authenticate(self.owner)\n        self.assertTrue(self.action(room,"admission",{"open":True}).data["admission_open"])\n        self.client.force_authenticate(self.member)\n        self.assertEqual(self.action(room,"join").status_code,200)

    def test_late_member_may_join_and_leave_after_dealer_is_selected(self):
        room=self.create_room()
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.action(room,"add-computer").status_code,200)
        self.assertEqual(self.action(room,"start").status_code,200)
        self.client.force_authenticate(self.member)
        joined=self.action(room,"join")
        self.assertEqual(joined.status_code,200,joined.data)
        self.assertTrue(joined.data["practice_mode"])
        self.assertEqual(joined.data["stats_category"],"PRACTICE")
        left=self.action(room,"leave")
        self.assertEqual(left.status_code,200,left.data)
        self.assertFalse(CardPokerSeat.objects.filter(room_id=room,user=self.member).exists())

    def test_active_hand_blocks_seat_changes_and_table_close(self):
        room=self.create_room()
        CardPokerRoom.objects.filter(pk=room).update(hand_active=True)
        self.client.force_authenticate(self.member)
        self.assertEqual(self.action(room,"join").status_code,409)
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.action(room,"leave").status_code,409)
        self.assertEqual(self.action(room,"close").status_code,409)

    def test_human_only_table_is_separate_from_any_ai_table(self):
        room=self.create_room()
        self.client.force_authenticate(self.member)
        joined=self.action(room,"join")
        self.assertEqual(joined.data["stats_category"],"HUMAN_ONLINE")
        self.client.force_authenticate(self.owner)
        # Existing room state is still waiting, so adding an AI marks practice.
        self.assertEqual(self.action(room,"add-computer").data["stats_category"],"PRACTICE")
