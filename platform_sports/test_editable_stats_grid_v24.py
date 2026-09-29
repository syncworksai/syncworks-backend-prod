from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from platform_social.models import GroupMembership, SocialGroup
from platform_sports.league_models import (
    LeagueDivision,
    LeagueSeason,
    LeagueTeamEntry,
    SportsOrganization,
)
from platform_sports.league_views import division_team_stats
from platform_sports.models import SoftballPlateAppearance, SportsGame, SportsPlayer, SportsTeam
from platform_sports.ops_models import SoftballStatLedgerEntry
from platform_sports.ops_views import softball_stats_summary
from platform_sports.player_badges import card_progress
from platform_sports.views import softball_player_stats


User = get_user_model()


class EditableStatsGridTests(APITestCase):
    def setUp(self):
        self.manager = User.objects.create_user(
            username="stats-grid-manager",
            email="stats-grid@example.test",
            password="x",
        )
        self.group = SocialGroup.objects.create(
            name="Grid Team",
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
        self.team = SportsTeam.objects.create(
            group=self.group,
            sport=SportsTeam.Sport.SOFTBALL,
            season_name="Fall 2026",
            created_by=self.manager,
        )
        self.player = SportsPlayer.objects.create(
            team=self.team,
            display_name="Grid Hitter",
            jersey_number="7",
            primary_position="2B",
            created_by=self.manager,
        )
        self.game = SportsGame.objects.create(
            team=self.team,
            game_type=SportsGame.GameType.LEAGUE,
            opponent_name="Official Opponent",
            start_at=timezone.now(),
            status=SportsGame.Status.FINAL,
            runs_for=1,
            runs_against=0,
            created_by=self.manager,
        )
        SoftballPlateAppearance.objects.create(
            game=self.game,
            player=self.player,
            sequence=1,
            inning=1,
            result=SoftballPlateAppearance.Result.SINGLE,
            rbi=1,
            runs_scored=1,
            created_by=self.manager,
        )

        self.other_group = SocialGroup.objects.create(
            name="Other Grid Team",
            kind=SocialGroup.Kind.TEAM,
            visibility=SocialGroup.Visibility.PUBLIC,
            created_by=self.manager,
        )
        self.other_team = SportsTeam.objects.create(
            group=self.other_group,
            sport=SportsTeam.Sport.SOFTBALL,
            season_name="Fall 2026",
            created_by=self.manager,
        )
        self.other_player = SportsPlayer.objects.create(
            team=self.other_team,
            display_name="Other Hitter",
            created_by=self.manager,
        )

        self.organization = SportsOrganization.objects.create(
            name="Grid League",
            slug="grid-league",
            sport="SOFTBALL",
            created_by=self.manager,
        )
        self.season = LeagueSeason.objects.create(
            organization=self.organization,
            name="Fall 2026",
            status=LeagueSeason.Status.ACTIVE,
            is_current=True,
            created_by=self.manager,
        )
        self.division = LeagueDivision.objects.create(
            season=self.season,
            name="Men",
        )
        LeagueTeamEntry.objects.create(division=self.division, team=self.team)
        LeagueTeamEntry.objects.create(division=self.division, team=self.other_team)

        self.client.force_authenticate(self.manager)

    def adjust(self, **overrides):
        totals = {
            "games": 4,
            "pa": 24,
            "ab": 20,
            "hits": 11,
            "doubles": 3,
            "triples": 1,
            "home_runs": 2,
            "walks": 3,
            "sac_flies": 1,
            "rbi": 12,
            "runs": 10,
        }
        totals.update(overrides)
        return self.client.post(
            "/api/v1/sports/stat-ledger/adjust-totals/",
            {
                "team": self.team.id,
                "player": self.player.id,
                "scope": "LEAGUE",
                "totals": totals,
                "note": "Coach verified grid totals",
            },
            format="json",
        )

    def test_grid_sets_visible_totals_and_feeds_lineup_badges_and_league_leaders(self):
        response = self.adjust()
        self.assertEqual(response.status_code, 200, response.data)
        row = response.data["row"]
        self.assertEqual(row["g"], 4)
        self.assertEqual(row["pa"], 24)
        self.assertEqual(row["ab"], 20)
        self.assertEqual(row["h"], 11)
        self.assertEqual(row["double"], 3)
        self.assertEqual(row["triple"], 1)
        self.assertEqual(row["hr"], 2)
        self.assertEqual(row["bb"], 3)
        self.assertEqual(row["sf"], 1)
        self.assertEqual(row["rbi"], 12)
        self.assertEqual(row["runs"], 10)
        self.assertEqual(row["avg"], 0.55)

        dashboard_row = next(
            item for item in softball_player_stats(self.team)
            if int(item["player"]["id"]) == self.player.id
        )
        self.assertEqual(dashboard_row["g"], 4)
        self.assertEqual(dashboard_row["h"], 11)
        self.assertEqual(dashboard_row["rbi"], 12)

        card = card_progress(self.player)
        self.assertEqual(card["season_totals"]["h"], 11)
        self.assertEqual(card["season_totals"]["ab"], 20)
        badges = {item["key"]: item for item in card["badges"]}
        self.assertEqual(badges["POWER"]["tier"], "SILVER")
        self.assertEqual(badges["CONTACT"]["tier"], "SILVER")

        league = division_team_stats(self.division)
        avg_leaders = league["leaders"]["avg"]
        leader = next(item for item in avg_leaders if item["player"]["id"] == self.player.id)
        self.assertEqual(leader["avg"], 0.55)
        self.assertEqual(leader["hr"], 2)
        self.assertEqual(leader["rbi"], 12)

    def test_second_grid_edit_can_reduce_a_previous_total_with_signed_audit_delta(self):
        first = self.adjust()
        self.assertEqual(first.status_code, 200, first.data)
        second = self.adjust(hits=10, doubles=2)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(second.data["row"]["h"], 10)
        self.assertEqual(second.data["row"]["double"], 2)
        self.assertEqual(second.data["row"]["avg"], 0.5)

        correction = SoftballStatLedgerEntry.objects.filter(
            team=self.team,
            player=self.player,
            source=SoftballStatLedgerEntry.Source.CORRECTION,
        ).order_by("-id").first()
        self.assertIsNotNone(correction)
        self.assertEqual(correction.hits, -1)
        self.assertEqual(correction.doubles, -1)

        summary = softball_stats_summary(self.team, "LEAGUE")
        row = next(item for item in summary if item["player"]["id"] == self.player.id)
        self.assertEqual(row["h"], 10)
        self.assertEqual(row["double"], 2)

    def test_grid_rejects_impossible_hit_breakdown(self):
        response = self.adjust(hits=3, doubles=2, triples=1, home_runs=2)
        self.assertEqual(response.status_code, 400)
        self.assertIn("cannot exceed", response.data["detail"])
