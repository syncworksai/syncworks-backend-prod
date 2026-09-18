from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from personal_calendar.models import PersonalCalendarEvent
from platform_social.models import GroupMembership, SocialGroup

from .league_models import SoftballRuleSet, SportsOrganization
from .models import SoftballPlateAppearance, SportsGame, SportsLineupSpot, SportsPlayer, SportsTeam

User = get_user_model()

class SoftballSportsApiTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="sports-owner",
            email="sports-owner@example.com",
            password="pass12345",
        )
        self.member = User.objects.create_user(
            username="sports-member",
            email="sports-member@example.com",
            password="pass12345",
        )
        self.group = SocialGroup.objects.create(
            name="Bed Springs Test",
            kind=SocialGroup.Kind.TEAM,
            created_by=self.owner,
        )
        GroupMembership.objects.create(
            group=self.group,
            user=self.owner,
            role=GroupMembership.Role.OWNER,
            status=GroupMembership.Status.ACTIVE,
            invited_by=self.owner,
        )
        GroupMembership.objects.create(
            group=self.group,
            user=self.member,
            role=GroupMembership.Role.MEMBER,
            status=GroupMembership.Status.ACTIVE,
            invited_by=self.owner,
        )
        self.team = SportsTeam.objects.create(
            group=self.group,
            sport=SportsTeam.Sport.SOFTBALL,
            season_name="Fall 2026",
            created_by=self.owner,
        )
        self.players = [
            SportsPlayer.objects.create(
                team=self.team,
                display_name=name,
                jersey_number=str(number),
                sort_order=index,
                created_by=self.owner,
            )
            for index, (name, number) in enumerate(
                (("Player One", 7), ("Player Two", 2), ("Player Three", 13)),
                start=1,
            )
        ]
        self.game = SportsGame.objects.create(
            team=self.team,
            opponent_name="Visitors",
            start_at=timezone.now() + timedelta(days=1),
            created_by=self.owner,
        )
        for order, player in enumerate(self.players, start=1):
            SportsLineupSpot.objects.create(
                game=self.game,
                player=player,
                batting_order=order,
                defensive_position=("2B", "SS", "OF")[order - 1],
            )
        self.client.force_authenticate(user=self.owner)

    def test_fixed_home_run_rule_blocks_extra_hr(self):
        organization = SportsOrganization.objects.create(
            name="Rule Test League",
            slug="rule-test-league",
            sport="SOFTBALL",
            created_by=self.owner,
        )
        rules = SoftballRuleSet.objects.create(
            organization=organization,
            name="Three HR",
            competition_type="LEAGUE",
            home_run_rule="FIXED",
            home_run_limit=1,
            created_by=self.owner,
        )
        self.game.rule_set = rules
        self.game.status = SportsGame.Status.LIVE
        self.game.save(update_fields=("rule_set", "status", "updated_at"))
        SoftballPlateAppearance.objects.create(
            game=self.game,
            player=self.players[0],
            sequence=1,
            inning=1,
            result=SoftballPlateAppearance.Result.HOME_RUN,
            created_by=self.owner,
        )
        response = self.client.post(
            reverse("sports-games-play", args=[self.game.id]),
            {"result": "HR", "rbi": 1, "runs_scored": 1},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["code"], "HOME_RUN_RULE")

    def test_one_up_rule_uses_opponent_hr_count(self):
        organization = SportsOrganization.objects.create(
            name="One Up League",
            slug="one-up-league",
            sport="SOFTBALL",
            created_by=self.owner,
        )
        rules = SoftballRuleSet.objects.create(
            organization=organization,
            name="San Diego",
            competition_type="LEAGUE",
            home_run_rule="ONE_UP",
            home_run_max_ahead=1,
            created_by=self.owner,
        )
        self.game.rule_set = rules
        self.game.status = SportsGame.Status.LIVE
        self.game.home_runs_against = 0
        self.game.save(update_fields=("rule_set", "status", "home_runs_against", "updated_at"))
        SoftballPlateAppearance.objects.create(
            game=self.game,
            player=self.players[0],
            sequence=1,
            inning=1,
            result=SoftballPlateAppearance.Result.HOME_RUN,
            created_by=self.owner,
        )
        blocked = self.client.post(
            reverse("sports-games-play", args=[self.game.id]),
            {"result": "HR", "rbi": 1, "runs_scored": 1},
            format="json",
        )
        self.assertEqual(blocked.status_code, status.HTTP_409_CONFLICT)

        opponent = self.client.post(
            reverse("sports-games-opponent-home-runs", args=[self.game.id]),
            {"home_runs_against": 1},
            format="json",
        )
        self.assertEqual(opponent.status_code, status.HTTP_200_OK)

        allowed = self.client.post(
            reverse("sports-games-play", args=[self.game.id]),
            {"result": "HR", "rbi": 1, "runs_scored": 1},
            format="json",
        )
        self.assertEqual(allowed.status_code, status.HTTP_201_CREATED)

    def test_defensive_position_change_preserves_batting_order(self):
        before = list(
            SportsLineupSpot.objects.filter(game=self.game)
            .order_by("batting_order")
            .values_list("player_id", "batting_order")
        )
        response = self.client.post(
            reverse("sports-games-defensive-position", args=[self.game.id]),
            {"player": self.players[1].id, "defensive_position": "MM"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        spot = SportsLineupSpot.objects.get(game=self.game, player=self.players[1])
        self.assertEqual(spot.defensive_position, "MM")
        after = list(
            SportsLineupSpot.objects.filter(game=self.game)
            .order_by("batting_order")
            .values_list("player_id", "batting_order")
        )
        self.assertEqual(after, before)

    def test_game_creation_syncs_social_event_and_member_calendars(self):
        response = self.client.post(
            reverse("sports-games-list"),
            {
                "team": self.team.id,
                "game_type": "TOURNAMENT",
                "opponent_name": "Tournament Team",
                "tournament_name": "Fall Classic",
                "round_label": "Pool A",
                "home_away": "NEUTRAL",
                "start_at": (timezone.now() + timedelta(days=5)).isoformat(),
                "venue_name": "Field 1",
                "city": "Montgomery",
                "state": "AL",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        game = SportsGame.objects.get(pk=response.data["id"])
        self.assertIsNotNone(game.social_event_id)
        self.assertEqual(game.social_event.organizer_group_id, self.group.id)
        self.assertTrue(
            PersonalCalendarEvent.objects.filter(
                owner=self.member,
                metadata__social_event_id=game.social_event_id,
            ).exists()
        )

    def test_three_outs_advance_inning_and_rotate_batter(self):
        start = self.client.post(reverse("sports-games-start", args=[self.game.id]), {}, format="json")
        self.assertEqual(start.status_code, status.HTTP_200_OK)

        for _ in range(3):
            play = self.client.post(
                reverse("sports-games-play", args=[self.game.id]),
                {"result": "OUT"},
                format="json",
            )
            self.assertEqual(play.status_code, status.HTTP_201_CREATED)

        self.game.refresh_from_db()
        self.assertEqual(self.game.current_inning, 2)
        self.assertEqual(self.game.outs, 0)
        self.assertEqual(self.game.current_batter_order, 1)
        self.assertEqual(SoftballPlateAppearance.objects.filter(game=self.game).count(), 3)

    def test_hit_updates_score_stats_and_undo_rewinds_state(self):
        self.client.post(reverse("sports-games-start", args=[self.game.id]), {}, format="json")
        play = self.client.post(
            reverse("sports-games-play", args=[self.game.id]),
            {"result": "2B", "rbi": 2, "runs_scored": 2},
            format="json",
        )
        self.assertEqual(play.status_code, status.HTTP_201_CREATED)
        self.game.refresh_from_db()
        self.assertEqual(self.game.runs_for, 2)
        self.assertEqual(self.game.current_batter_order, 2)

        stats_response = self.client.get(reverse("sports-teams-stats", args=[self.team.id]))
        self.assertEqual(stats_response.status_code, status.HTTP_200_OK)
        first = next(row for row in stats_response.data if row["player"]["id"] == self.players[0].id)
        self.assertEqual(first["ab"], 1)
        self.assertEqual(first["h"], 1)
        self.assertEqual(first["double"], 1)
        self.assertEqual(first["rbi"], 2)
        self.assertEqual(first["avg"], 1.0)
        self.assertEqual(first["slg"], 2.0)

        undo = self.client.post(reverse("sports-games-undo", args=[self.game.id]), {}, format="json")
        self.assertEqual(undo.status_code, status.HTTP_200_OK)
        self.game.refresh_from_db()
        self.assertEqual(self.game.runs_for, 0)
        self.assertEqual(self.game.current_batter_order, 1)
        self.assertFalse(SoftballPlateAppearance.objects.filter(game=self.game).exists())

    def test_plain_member_cannot_enter_live_game_data(self):
        self.client.force_authenticate(user=self.member)
        response = self.client.post(reverse("sports-games-start", args=[self.game.id]), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
