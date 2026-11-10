from unittest.mock import patch
import time

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from platform_social.models import CardPokerRoom, GroupMembership, SocialGroup
from platform_social.online_poker import _score

User = get_user_model()


def c(rank, suit="S"):
    return {"rank": rank, "suit": suit}


class OnlinePokerTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="online-host", email="host@example.com", password="test")
        self.friend = User.objects.create_user(username="online-friend", email="friend@example.com", password="test")
        self.outsider = User.objects.create_user(username="online-outsider", email="outsider@example.com", password="test")
        self.group = SocialGroup.objects.create(name="Remote Card Night", kind="CLUB", created_by=self.owner)
        for user, role in [(self.owner, "OWNER"), (self.friend, "MEMBER")]:
            GroupMembership.objects.create(group=self.group, user=user, role=role, status="ACTIVE")
        self.client.force_authenticate(self.owner)
        response = self.client.post(reverse("social-card-rooms"), {
            "group": self.group.id, "name": "Saturday Poker", "capacity": 6,
            "virtual_buy_in_cents": 2000,
        })
        self.assertEqual(response.status_code, 201, response.data)
        self.room = response.data["id"]
        self.base = reverse("social-card-room-game", kwargs={"room_id": self.room})
        self.actions = reverse("social-card-room-action", kwargs={"room_id": self.room, "verb": "join"})
        self.client.force_authenticate(self.friend)
        self.assertEqual(self.client.post(self.actions).status_code, 200)
        self.client.force_authenticate(self.owner)
        for verb, payload in [
            ("start", {}),
            ("configure", {"game_code": "357", "game_selection": "DEALER", "ante_cents": 25, "pot_cap_cents": 1000}),
        ]:
            response = self.client.post(reverse("social-card-room-action", kwargs={"room_id": self.room, "verb": verb}), payload)
            self.assertEqual(response.status_code, 200, response.data)

    def game(self, user, action=None):
        self.client.force_authenticate(user)
        if action:
            return self.client.post(self.base, {"action": action})
        return self.client.get(self.base)

    def start(self):
        result = self.game(self.owner, "start")
        self.assertEqual(result.status_code, 200, result.data)
        return result.data

    def test_cards_are_private_by_authenticated_user(self):
        host = self.start()
        friend = self.game(self.friend).data
        self.assertEqual(host["phase"], "choosing")
        self.assertEqual(friend["phase"], "choosing")
        self.assertEqual(host["version"], friend["version"])
        self.assertEqual(len(host["my_hand"]), 3)
        self.assertEqual(len(friend["my_hand"]), 3)
        self.assertNotEqual(host["my_hand"], friend["my_hand"])
        self.assertEqual(host["revealed_holders"], {})
        self.assertEqual(friend["revealed_holders"], {})
        self.assertNotIn("deck", host)
        self.assertNotIn("hands", host)
        self.assertEqual(host["pot_cents"], 50)
        self.assertEqual(self.game(self.outsider).status_code, 404)

    def test_reveal_only_to_holders_after_server_settlement(self):
        host = self.start()
        self.assertEqual(self.game(self.owner, "hold").status_code, 200)
        self.assertEqual(self.game(self.friend, "hold").status_code, 200)
        host = self.game(self.owner).data
        friend = self.game(self.friend).data
        self.assertEqual(host["phase"], "result")
        self.assertEqual(friend["version"], host["version"])
        self.assertEqual(len(host["revealed_holders"]), 2)
        self.assertEqual(len(friend["revealed_holders"]), 2)
        self.assertIn(host["result"]["type"], {"tie", "round_winner"})
        self.assertEqual(self.game(self.owner, "hold").status_code, 409)

    def test_dropped_players_cannot_see_holders_cards(self):
        self.start()
        self.game(self.owner, "drop")
        self.game(self.friend, "hold")
        host = self.game(self.owner).data
        friend = self.game(self.friend).data
        self.assertEqual(host["revealed_holders"], {})
        self.assertEqual(len(friend["revealed_holders"]), 1)
        self.assertEqual(friend["result"]["type"], "uncontested")
        self.assertEqual(friend["players"][1]["strikes"], 1)

    def test_continue_advances_every_phone_at_same_server_deadline(self):
        self.start()
        self.game(self.owner, "drop")
        self.game(self.friend, "hold")
        now = time.time()
        with patch("platform_social.online_poker.time.time", return_value=now):
            continued = self.game(self.friend, "continue")
        self.assertEqual(continued.data["phase"], "continue")
        self.assertAlmostEqual(continued.data["continue_deadline"], now + 10)
        with patch("platform_social.online_poker.time.time", return_value=now + 11):
            guest = self.game(self.friend).data
        self.assertEqual(guest["street"], 1)
        self.assertEqual(guest["phase"], "choosing")
        self.assertEqual(len(guest["my_hand"]), 5)
        host = self.game(self.owner).data
        self.assertEqual(host["version"], guest["version"])
        self.assertEqual(len(host["my_hand"]), 5)
        self.assertEqual(host["revealed_holders"], {})

    def test_unanswered_decisions_auto_drop_on_shared_deadline(self):
        self.start()
        with patch("platform_social.online_poker.time.time", return_value=999999999999.0):
            data = self.game(self.friend).data
        self.assertEqual(data["phase"], "result")
        self.assertEqual(data["result"]["type"], "carry")
        self.assertEqual(data["pot_cents"], 50)
        self.assertEqual(data["revealed_holders"], {})

    def test_only_host_may_start_and_no_second_start(self):
        self.assertEqual(self.game(self.friend, "start").status_code, 403)
        self.start()
        self.assertEqual(self.game(self.owner, "start").status_code, 409)

    def test_existing_room_lobby_prevents_joins_during_server_hand(self):
        self.start()
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.post(self.actions).status_code, 404)
        self.client.force_authenticate(self.owner)
        self.assertTrue(CardPokerRoom.objects.get(pk=self.room).hand_active)

    def test_3_card_wild_hand_rank_and_5_card_rank(self):
        self.assertEqual(_score([c(3), c(14), c(14)], 0)[1], "Three of a kind")
        self.assertEqual(_score([c(5), c(10), c(10, "H"), c(10, "D"), c(2)], 1)[1], "Four of a kind")
