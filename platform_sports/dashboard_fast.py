"""Bounded-query team dashboard for mobile. Avoid serializing the same games twice."""
from collections import defaultdict

from django.db.models import Prefetch
from django.utils import timezone

from platform_social.models import GroupMembership

from .models import (
    SoftballPlateAppearance, SportsGame, SportsLineupSpot, SportsPlayer,
    SportsSubstitution, SportsTeam,
)
from .serializers import (
    SportsLineupSpotSerializer, SportsPlayerSerializer,
    SportsSubstitutionSerializer, SportsTeamSerializer,
)


HITS = {"1B", "2B", "3B", "HR"}


def _ratio(numerator, denominator):
    return round(numerator / denominator, 3) if denominator else 0.0


def fast_team_dashboard(team, user, player_stats):
    """Return the manager dashboard contract with prefetched game summaries.

    Full game detail stays available at /sports/games/<id>/. No photos, deep
    social-event trees, or per-game database lookups are needed for the hub.
    """
    players = list(
        team.players.filter(is_active=True, merged_into__isnull=True)
        .select_related("user")
        .order_by("sort_order", "display_name", "id")
    )
    player_data = SportsPlayerSerializer(players, many=True).data
    player_map = {player.id: data for player, data in zip(players, player_data)}
    can_manage = GroupMembership.objects.filter(
        group_id=team.group_id,
        user=user,
        status=GroupMembership.Status.ACTIVE,
        role__in=("OWNER", "DIRECTOR", "MANAGER"),
    ).exists()
    can_score = can_manage or GroupMembership.objects.filter(
        group_id=team.group_id, user=user, status=GroupMembership.Status.ACTIVE,
        role=GroupMembership.Role.SCOREKEEPER,
    ).exists()

    games = list(
        team.games.exclude(status=SportsGame.Status.CANCELLED)
        .select_related("team__group", "rule_set", "social_event")
        .prefetch_related(
            Prefetch(
                "lineup_spots",
                queryset=SportsLineupSpot.objects.select_related("player__user").order_by("batting_order", "id"),
            ),
            Prefetch(
                "substitutions",
                queryset=SportsSubstitution.objects.select_related("outgoing_player__user", "incoming_player__user"),
            ),
            "inning_lines",
            "plate_appearances",
        )
        .order_by("start_at", "id")
    )
    final_games = [game for game in games if game.status == SportsGame.Status.FINAL]
    wins = sum(game.runs_for > game.runs_against for game in final_games)
    losses = sum(game.runs_for < game.runs_against for game in final_games)
    ties = len(final_games) - wins - losses

    def game_summary(game):
        spots = list(game.lineup_spots.all())
        spot_ids = {spot.player_id for spot in spots}
        appearances = list(game.plate_appearances.all())
        home_runs = sum(pa.result == "HR" for pa in appearances)
        rules = game.rule_set
        home_run_allowed = True
        if rules:
            if rules.home_run_rule == "FIXED":
                home_run_allowed = rules.home_run_limit is None or home_runs < rules.home_run_limit
            elif rules.home_run_rule == "ONE_UP":
                home_run_allowed = home_runs < (
                    int(game.home_runs_against or 0) + int(rules.home_run_max_ahead or 1)
                )
        hits_by_inning = defaultdict(int)
        for pa in appearances:
            if pa.result in HITS:
                hits_by_inning[pa.inning] += 1
        innings = [
            {
                "id": row.id, "game": game.id, "inning": row.inning,
                "team_runs": row.team_runs, "opponent_runs": row.opponent_runs,
                "team_hits": hits_by_inning.get(row.inning, 0),
                "opponent_hits": row.opponent_hits,
            }
            for row in game.inning_lines.all()
        ]
        batting_spot = next(
            (spot for spot in spots if spot.batting_order == game.current_batter_order), None
        )
        return {
            "id": game.id,
            "team": team.id, "team_name": team.group.name,
            "social_event": game.social_event_id,
            "social_event_detail": None,
            "game_type": game.game_type,
            "opponent_name": game.opponent_name,
            "tournament_name": game.tournament_name,
            "round_label": game.round_label,
            "home_away": game.home_away,
            "start_at": game.start_at, "end_at": game.end_at,
            "timezone": game.timezone, "venue_name": game.venue_name,
            "address_line1": game.address_line1, "city": game.city,
            "state": game.state, "notes": game.notes,
            "innings_scheduled": game.innings_scheduled,
            "rule_set": game.rule_set_id,
            "rule_set_detail": (
                {
                    "id": rules.id, "name": rules.name,
                    "competition_type": rules.competition_type,
                    "innings": rules.innings, "home_run_rule": rules.home_run_rule,
                    "home_run_limit": rules.home_run_limit,
                    "home_run_max_ahead": rules.home_run_max_ahead,
                    "notes": rules.notes,
                } if rules else None
            ),
            "home_runs_for": home_runs,
            "home_runs_against": game.home_runs_against,
            "home_run_allowed": home_run_allowed,
            "gamecast_enabled": game.gamecast_enabled,
            "gamecast_token": str(game.gamecast_token),
            "gamecast_show_batter": game.gamecast_show_batter,
            "gamecast_show_recent_plays": game.gamecast_show_recent_plays,
            "status": game.status, "current_inning": game.current_inning,
            "outs": game.outs, "current_batter_order": game.current_batter_order,
            "current_batter": player_map.get(batting_spot.player_id) if batting_spot else None,
            "runs_for": game.runs_for, "runs_against": game.runs_against,
            "started_at": game.started_at, "ended_at": game.ended_at,
            "plate_appearance_count": len(appearances),
            "lineup_spots": SportsLineupSpotSerializer(spots, many=True).data,
            "substitutions": SportsSubstitutionSerializer(list(game.substitutions.all()), many=True).data,
            "bench_players": [data for player_id, data in player_map.items() if player_id not in spot_ids],
            "can_manage": can_manage, "can_score": can_score,
            "inning_lines": innings,
            "created_at": game.created_at, "updated_at": game.updated_at,
        }

    summaries = [game_summary(game) for game in games]
    now = timezone.now()
    upcoming = [
        row for row in summaries if row["status"] == SportsGame.Status.SCHEDULED and row["start_at"] >= now
    ]
    overdue = [
        row for row in summaries if row["status"] == SportsGame.Status.SCHEDULED and row["start_at"] < now
    ]
    recent = [row for row in summaries if row["status"] == SportsGame.Status.FINAL]
    live = [row for row in summaries if row["status"] == SportsGame.Status.LIVE]

    team_ab = sum(row["ab"] for row in player_stats)
    team_hits = sum(row["h"] for row in player_stats)
    team_walks = sum(row["bb"] for row in player_stats)
    team_sf = sum(row["sf"] for row in player_stats)
    team_tb = sum(row["tb"] for row in player_stats)
    team_obp = _ratio(team_hits + team_walks, team_ab + team_walks + team_sf)
    team_slg = _ratio(team_tb, team_ab)

    return {
        "team": SportsTeamSerializer(team).data,
        "record": {"wins": wins, "losses": losses, "ties": ties, "games": len(final_games)},
        "team_stats": {
            "avg": _ratio(team_hits, team_ab),
            "hits": team_hits, "at_bats": team_ab,
            "plate_appearances": sum(row["pa"] for row in player_stats),
            "home_runs": sum(row["hr"] for row in player_stats),
            "doubles": sum(row["double"] for row in player_stats),
            "triples": sum(row["triple"] for row in player_stats),
            "walks": team_walks, "rbi": sum(row["rbi"] for row in player_stats),
            "obp": team_obp, "slg": team_slg, "ops": round(team_obp + team_slg, 3),
            "runs_for": sum(game.runs_for for game in final_games),
            "runs_against": sum(game.runs_against for game in final_games),
        },
        "players": player_data,
        "player_stats": player_stats,
        "upcoming_games": upcoming[:8],
        "needs_completion_games": list(reversed(overdue))[:8],
        "recent_games": list(reversed(recent))[:8],
        "live_games": live,
    }
