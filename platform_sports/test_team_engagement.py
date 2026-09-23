from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from platform_social.models import EventMemberResponse, GroupMembership, SocialGroup
from platform_sports.models import SoftballPlateAppearance, SportsGame, SportsPlayer, SportsTeam
from platform_sports.ops_models import SportsCoachAward, SportsPlayerProfile, SportsWeeklyPoll
from platform_sports.player_badges import card_progress
from user_accounts.models import Notification

User = get_user_model()


class SportsEngagementTests(APITestCase):
    def setUp(self):
        self.coach = User.objects.create_user(username="eng-coach", email="coach@example.test", password="p")
        self.jake = User.objects.create_user(username="eng-jake", email="jake@example.test", password="p")
        self.ethan = User.objects.create_user(username="eng-ethan", email="ethan@example.test", password="p")
        self.outsider = User.objects.create_user(username="eng-outsider", email="outside@example.test", password="p")
        self.group = SocialGroup.objects.create(
            name="Test Bed Springs", kind=SocialGroup.Kind.TEAM,
            visibility=SocialGroup.Visibility.PRIVATE, created_by=self.coach,
        )
        for who, role in (
            (self.coach, GroupMembership.Role.OWNER),
            (self.jake, GroupMembership.Role.MEMBER),
            (self.ethan, GroupMembership.Role.MEMBER),
        ):
            GroupMembership.objects.create(
                group=self.group, user=who, role=role,
                status=GroupMembership.Status.ACTIVE, invited_by=self.coach,
            )
        self.team = SportsTeam.objects.create(
            group=self.group, sport=SportsTeam.Sport.SOFTBALL,
            season_name="Fall 2026", created_by=self.coach,
        )
        self.player1 = SportsPlayer.objects.create(
            team=self.team, user=self.jake, display_name="Jake",
            created_by=self.coach,
        )
        self.player2 = SportsPlayer.objects.create(
            team=self.team, user=self.ethan, display_name="Ethan",
            created_by=self.coach,
        )
        self.profile1 = SportsPlayerProfile.objects.create(
            player=self.player1, email=self.jake.email,
            birth_date=date(1988, 6, 12),
        )
        today = timezone.localdate()
        monday = today - timedelta(days=today.weekday()) + timedelta(days=7)
        self.week = monday.isoformat()
        tz = ZoneInfo("America/Chicago")
        self.games = [
            SportsGame.objects.create(
                team=self.team, opponent_name=name, start_at=datetime.combine(monday, time(hour, 30), tzinfo=tz),
                home_away=location, created_by=self.coach,
            )
            for name, hour, location in [
                ("First game", 18, SportsGame.HomeAway.HOME),
                ("Second game", 19, SportsGame.HomeAway.AWAY),
            ]
        ]
        self.base = f"/api/v1/sports/team-engagement/{self.team.pk}/"
        self.client.force_authenticate(self.coach)

    def publish(self):
        return self.client.post(
            self.base + "weekly/",
            {"week_start": self.week, "message": "Answer for both games"}, format="json",
        )

    def test_weekly_publish_one_notification_and_independent_game_responses(self):
        first = self.publish()
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(SportsWeeklyPoll.objects.filter(team=self.team).count(), 1)
        self.assertTrue(all(game.social_event_id is not None for game in SportsGame.objects.filter(pk__in=[g.pk for g in self.games])))
        self.assertEqual(Notification.objects.filter(recipient=self.jake, data__kind="WEEKLY_RSVP").count(), 1)
        self.assertEqual(Notification.objects.filter(recipient=self.ethan, data__kind="WEEKLY_RSVP").count(), 1)
        self.assertEqual(self.publish().status_code, 200)
        self.assertEqual(Notification.objects.filter(recipient=self.jake, data__kind="WEEKLY_RSVP").count(), 1)

        self.client.force_authenticate(self.jake)
        self.assertTrue(self.client.get(self.base + "weekly/").data["weeks"][0]["my_pending"])
        answers = self.client.post(
            self.base + "weekly/respond/",
            {"week_start": self.week, "selections": [
                {"game": self.games[0].id, "response": "YES"},
                {"game": self.games[1].id, "response": "NO"},
            ]}, format="json",
        )
        self.assertEqual(answers.status_code, 200, answers.data)
        self.assertFalse(answers.data["my_pending"])
        self.games[0].refresh_from_db()
        self.games[1].refresh_from_db()
        self.assertEqual(EventMemberResponse.objects.get(
            event=self.games[0].social_event, user=self.jake,
        ).response, "YES")
        self.assertEqual(EventMemberResponse.objects.get(
            event=self.games[1].social_event, user=self.jake,
        ).response, "NO")
        self.client.force_authenticate(self.coach)
        overview = self.client.get(self.base + "weekly/").data["weeks"][0]
        self.assertEqual(overview["games"][0]["counts"]["YES"], 1)
        self.assertEqual(overview["games"][1]["counts"]["NO"], 1)
        self.assertEqual(overview["pending_players"], 1)

    def test_partial_or_wrong_game_submission_is_rejected_atomically(self):
        self.publish()
        self.client.force_authenticate(self.jake)
        partial = self.client.post(self.base + "weekly/respond/", {
            "week_start": self.week,
            "selections": [{"game": self.games[0].pk, "response": "YES"}],
        }, format="json")
        self.assertEqual(partial.status_code, 400)
        self.assertEqual(EventMemberResponse.objects.filter(
            event__in=[game.social_event for game in SportsGame.objects.filter(pk__in=[g.pk for g in self.games])],
            user=self.jake, response="YES",
        ).count(), 0)
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get(self.base + "weekly/").status_code, 403)

    def test_general_chat_poll_one_vote_per_account_and_coach_close(self):
        made = self.client.post(self.base + "polls/", {
            "question": "Which practice night works?", "options": ["Monday", "Thursday"],
        }, format="json")
        self.assertEqual(made.status_code, 201, made.data)
        poll = made.data["id"]
        self.client.force_authenticate(self.jake)
        url = self.base + f"polls/{poll}/vote/"
        self.assertEqual(self.client.post(url, {"option_index": 0}, format="json").status_code, 200)
        changed = self.client.post(url, {"option_index": 1}, format="json")
        self.assertEqual(changed.status_code, 200, changed.data)
        self.assertEqual(changed.data["counts"], [0, 1])
        self.client.force_authenticate(self.coach)
        self.assertEqual(self.client.post(self.base + f"polls/{poll}/close/").status_code, 200)
        self.client.force_authenticate(self.jake)
        self.assertEqual(self.client.post(url, {"option_index": 0}, format="json").status_code, 409)

    def test_dob_is_private_and_coach_awards_do_not_fake_hits(self):
        profile_url = f"/api/v1/sports/player-profiles/{self.profile1.id}/"
        self.client.force_authenticate(self.ethan)
        self.assertEqual(self.client.get(profile_url).status_code, 404)
        self.client.force_authenticate(self.jake)
        mine = self.client.get(profile_url)
        self.assertEqual(mine.status_code, 200)
        self.assertEqual(mine.data["birth_date"], "1988-06-12")
        self.assertFalse(mine.data["show_age"])
        self.assertGreaterEqual(mine.data["age"], 35)
        self.assertEqual(self.client.patch(profile_url, {
            "show_age": True, "birth_date": "1988-06-12",
        }, format="json").status_code, 200)

        award_url = "/api/v1/sports/coach-awards/"
        unauthorized = self.client.post(award_url, {
            "team": self.team.pk, "player": self.player1.pk,
            "kind": "ROOKIE_YEAR", "season_name": "Fall 2026", "reason": "First season",
        }, format="json")
        self.assertEqual(unauthorized.status_code, 400)
        self.client.force_authenticate(self.coach)
        award = self.client.post(award_url, {
            "team": self.team.pk, "player": self.player1.pk,
            "kind": "ROOKIE_YEAR", "season_name": "Fall 2026",
            "reason": "Coach-selected after the season",
        }, format="json")
        self.assertEqual(award.status_code, 201, award.data)
        self.assertEqual(Notification.objects.filter(recipient=self.jake, data__kind="COACH_AWARD").count(), 1)
        duplicate = self.client.post(award_url, {
            "team": self.team.pk, "player": self.player2.pk, "kind": "ROOKIE_YEAR",
            "season_name": "Fall 2026", "reason": "Other",
        }, format="json")
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(self.team.games.count(), 2)
        self.assertEqual(SoftballPlateAppearance.objects.filter(game__team=self.team).count(), 0)
        self.assertEqual(card_progress(self.player1)["career_totals"]["h"], 0)
        self.assertEqual(self.client.delete(award_url + str(award.data["id"]) + "/").status_code, 204)
        self.assertEqual(SportsCoachAward.objects.filter(revoked_at__isnull=True).count(), 0)

    def test_milestones_require_verified_finished_book(self):
        game = self.games[0]
        SoftballPlateAppearance.objects.create(
            game=game, player=self.player1, sequence=1, inning=1,
            result=SoftballPlateAppearance.Result.HOME_RUN,
            runs_scored=1, rbi=1, created_by=self.coach,
        )
        self.assertFalse(next(m for m in card_progress(self.player1)["milestones"] if m["key"] == "HOME_RUN_KING")["achieved"])
        game.status = SportsGame.Status.FINAL
        game.save(update_fields=("status", "updated_at"))
        self.assertTrue(next(m for m in card_progress(self.player1)["milestones"] if m["key"] == "HOME_RUN_KING")["achieved"])
