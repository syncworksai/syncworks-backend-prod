from __future__ import annotations

from datetime import timedelta
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.text import slugify
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from platform_social.models import GroupMembership

from .league_models import (
    LeagueDivision,
    LeagueGame,
    LeagueRosterEntry,
    LeagueSeason,
    LeagueTournament,
    LeagueTournamentBye,
    LeagueTournamentEntry,
    LeagueTeamEntry,
    SportsOrganization,
    SportsOrganizationMembership,
    SportsPlayerIdentity,
    SoftballRuleSet,
)
from .league_serializers import (
    LeagueDivisionSerializer,
    LeagueGameSerializer,
    LeagueRosterEntrySerializer,
    LeagueSeasonSerializer,
    LeagueTournamentByeSerializer,
    LeagueTournamentEntrySerializer,
    LeagueTournamentSerializer,
    LeagueTeamEntrySerializer,
    SportsOrganizationMembershipSerializer,
    SportsOrganizationSerializer,
    SportsPlayerIdentitySerializer,
    SoftballRuleSetSerializer,
)
from .models import SoftballPlateAppearance, SportsGame, SportsPlayer, SportsTeam
from .serializers import SportsPlayerSerializer, SportsTeamSerializer
from .views import AB_EXCLUDED_RESULTS, HIT_RESULTS, can_manage_team, sync_game_social_event

User = get_user_model()
ORG_MANAGEMENT_ROLES = (
    SportsOrganizationMembership.Role.COMMISSIONER,
    SportsOrganizationMembership.Role.ADMIN,
)


def can_manage_organization(user, organization):
    return SportsOrganizationMembership.objects.filter(
        organization=organization,
        user=user,
        status=SportsOrganizationMembership.Status.ACTIVE,
        role__in=ORG_MANAGEMENT_ROLES,
    ).exists()


def can_manage_division(user, division):
    return can_manage_organization(user, division.season.organization)


def user_can_view_organization(user, organization):
    if organization.is_public:
        return True
    return SportsOrganizationMembership.objects.filter(
        organization=organization,
        user=user,
        status=SportsOrganizationMembership.Status.ACTIVE,
    ).exists()


def unique_org_slug(name):
    base = slugify(name)[:175] or "league"
    slug = base
    number = 2
    while SportsOrganization.objects.filter(slug=slug).exists():
        slug = f"{base}-{number}"
        number += 1
    return slug


def _frontend_url():
    return str(getattr(settings, "SYNCWORKS_FRONTEND_URL", "") or getattr(settings, "FRONTEND_URL", "") or "https://syncworksapp.com").rstrip("/")


def _invite_urls(identity, roster):
    path = f"/sports/invite/{identity.claim_token}?roster={roster.id}"
    invite_url = f"{_frontend_url()}{path}"
    encoded_next = quote(path, safe="")
    encoded_email = quote(identity.email, safe="@+")
    return {
        "invite_url": invite_url,
        "register_url": f"{_frontend_url()}/register?email={encoded_email}&next={encoded_next}",
        "login_url": f"{_frontend_url()}/login?next={encoded_next}",
    }


def send_roster_invite_email(roster):
    identity = roster.identity
    urls = _invite_urls(identity, roster)
    team_name = roster.team.group.name
    league_name = roster.division.season.organization.name
    division_name = roster.division.name
    subject = f"Join {team_name} on SyncWorks"
    text = (
        f"You've been invited to {team_name} in {league_name} · {division_name}.\n\n"
        f"Open your invitation: {urls['invite_url']}\n\n"
        f"New to SyncWorks? Create your free account here: {urls['register_url']}\n"
        f"Already have SyncWorks? Sign in here: {urls['login_url']}\n\n"
        "After you sign in with this email, SyncWorks will link your player profile and team Social group."
    )
    html = f"""
    <div style="font-family:Arial,sans-serif;line-height:1.5;color:#0f172a">
      <h2 style="margin-bottom:8px">You're invited to {team_name}</h2>
      <p>{league_name} · {division_name}</p>
      <p>Your player invitation connects your roster profile, game schedule, team chat, lineup, stats and dues under one SyncWorks account.</p>
      <p><a href="{urls['invite_url']}" style="display:inline-block;padding:12px 18px;background:#22d3ee;color:#020617;text-decoration:none;border-radius:10px;font-weight:700">Open team invitation</a></p>
      <p style="font-size:13px;color:#475569">New to SyncWorks? The invitation page will take you through free signup, then return you to join the team automatically.</p>
    </div>
    """.strip()
    msg = EmailMultiAlternatives(
        subject=subject,
        body=text,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "SyncWorks <no-reply@syncworksapp.com>"),
        to=[identity.email],
    )
    msg.attach_alternative(html, "text/html")
    msg.send(fail_silently=True)
    return urls


def round_robin_rounds(teams):
    teams = list(teams)
    if len(teams) < 2:
        return []
    if len(teams) % 2:
        teams.append(None)
    fixed = teams[0]
    rotating = teams[1:]
    rounds = []
    for round_index in range(len(teams) - 1):
        current = [fixed] + rotating
        pairs = []
        half = len(current) // 2
        for index in range(half):
            left = current[index]
            right = current[-(index + 1)]
            if left is None or right is None:
                continue
            if round_index % 2:
                left, right = right, left
            pairs.append((left, right))
        rounds.append(pairs)
        rotating = [rotating[-1]] + rotating[:-1]
    return rounds


def _aware_datetime(value):
    parsed = parse_datetime(str(value or ""))
    if not parsed:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _game_type(source):
    return SportsGame.GameType.TOURNAMENT if source == LeagueGame.Source.TOURNAMENT else SportsGame.GameType.LEAGUE


def sync_league_game_records(league_game):
    common = {
        "start_at": league_game.start_at,
        "end_at": league_game.end_at,
        "timezone": league_game.timezone,
        "venue_name": league_game.venue_name,
        "address_line1": league_game.address_line1,
        "city": league_game.city,
        "state": league_game.state,
        "rule_set": league_game.rule_set,
        "game_type": _game_type(league_game.source),
        "tournament_name": league_game.tournament.name if league_game.tournament_id else "",
        "round_label": f"Round {league_game.round_number}" if league_game.round_number else "",
    }
    if league_game.home_sports_game_id:
        game = league_game.home_sports_game
        for key, value in common.items():
            setattr(game, key, value)
        game.opponent_name = league_game.away_team.group.name
        game.home_away = SportsGame.HomeAway.HOME
        game.runs_for = league_game.home_score
        game.runs_against = league_game.away_score
        if league_game.status == LeagueGame.Status.FINAL:
            game.status = SportsGame.Status.FINAL
        elif league_game.status == LeagueGame.Status.CANCELLED:
            game.status = SportsGame.Status.CANCELLED
        game.save()
        sync_game_social_event(game)
    if league_game.away_sports_game_id:
        game = league_game.away_sports_game
        for key, value in common.items():
            setattr(game, key, value)
        game.opponent_name = league_game.home_team.group.name
        game.home_away = SportsGame.HomeAway.AWAY
        game.runs_for = league_game.away_score
        game.runs_against = league_game.home_score
        if league_game.status == LeagueGame.Status.FINAL:
            game.status = SportsGame.Status.FINAL
        elif league_game.status == LeagueGame.Status.CANCELLED:
            game.status = SportsGame.Status.CANCELLED
        game.save()
        sync_game_social_event(game)


def create_league_game_records(league_game, user):
    common = {
        "game_type": _game_type(league_game.source),
        "tournament_name": league_game.tournament.name if league_game.tournament_id else "",
        "round_label": f"Round {league_game.round_number}" if league_game.round_number else "",
        "start_at": league_game.start_at,
        "end_at": league_game.end_at,
        "timezone": league_game.timezone,
        "venue_name": league_game.venue_name,
        "address_line1": league_game.address_line1,
        "city": league_game.city,
        "state": league_game.state,
        "rule_set": league_game.rule_set,
        "created_by": user,
    }
    home_game = SportsGame.objects.create(
        team=league_game.home_team,
        opponent_name=league_game.away_team.group.name,
        home_away=SportsGame.HomeAway.HOME,
        **common,
    )
    away_game = SportsGame.objects.create(
        team=league_game.away_team,
        opponent_name=league_game.home_team.group.name,
        home_away=SportsGame.HomeAway.AWAY,
        **common,
    )
    sync_game_social_event(home_game)
    sync_game_social_event(away_game)
    league_game.home_sports_game = home_game
    league_game.away_sports_game = away_game
    league_game.save(update_fields=("home_sports_game", "away_sports_game", "updated_at"))
    return league_game


def sync_league_result_from_sports_game(game):
    try:
        league_game = game.league_home_record
        is_home = True
    except LeagueGame.DoesNotExist:
        try:
            league_game = game.league_away_record
            is_home = False
        except LeagueGame.DoesNotExist:
            return None
    if is_home:
        league_game.home_score = game.runs_for
        league_game.away_score = game.runs_against
    else:
        league_game.home_score = game.runs_against
        league_game.away_score = game.runs_for
    league_game.status = LeagueGame.Status.FINAL if game.status == SportsGame.Status.FINAL else league_game.status
    league_game.save(update_fields=("home_score", "away_score", "status", "updated_at"))
    sync_league_game_records(league_game)
    return league_game


def _build_game(division, home_team, away_team, user, start_at, payload, *, source=LeagueGame.Source.LEAGUE, tournament=None, week_number=None, round_number=None, bracket_slot=None):
    rule_set = None
    rule_set_id = payload.get("rule_set")
    if rule_set_id:
        rule_set = SoftballRuleSet.objects.filter(pk=rule_set_id, organization=division.season.organization).first()
    game = LeagueGame.objects.create(
        division=division,
        tournament=tournament,
        source=source,
        home_team=home_team,
        away_team=away_team,
        rule_set=rule_set or (tournament.rule_set if tournament else None),
        start_at=start_at,
        end_at=start_at + timedelta(minutes=max(30, int(payload.get("game_minutes") or 60))),
        timezone=str(payload.get("timezone") or "America/Chicago"),
        venue_name=str(payload.get("venue_name") or ""),
        field_name=str(payload.get("field_name") or ""),
        address_line1=str(payload.get("address_line1") or ""),
        city=str(payload.get("city") or ""),
        state=str(payload.get("state") or ""),
        week_number=week_number,
        round_number=round_number,
        bracket_slot=bracket_slot,
        created_by=user,
    )
    game.full_clean()
    return create_league_game_records(game, user)


def division_standings(division):
    entries = list(
        LeagueTeamEntry.objects.filter(division=division, status=LeagueTeamEntry.Status.ACTIVE)
        .select_related("team__group")
    )
    rows = {
        entry.team_id: {
            "team": SportsTeamSerializer(entry.team).data,
            "wins": 0, "losses": 0, "ties": 0, "games": 0,
            "runs_for": 0, "runs_against": 0, "opponents": [],
        }
        for entry in entries
    }
    finals = list(
        LeagueGame.objects.filter(
            division=division,
            source=LeagueGame.Source.LEAGUE,
            status=LeagueGame.Status.FINAL,
        ).select_related("home_team__group", "away_team__group")
    )
    for game in finals:
        home = rows.get(game.home_team_id)
        away = rows.get(game.away_team_id)
        if not home or not away:
            continue
        for row, scored, allowed, opponent_id in (
            (home, game.home_score, game.away_score, game.away_team_id),
            (away, game.away_score, game.home_score, game.home_team_id),
        ):
            row["games"] += 1
            row["runs_for"] += int(scored or 0)
            row["runs_against"] += int(allowed or 0)
            row["opponents"].append(opponent_id)
        if game.home_score > game.away_score:
            home["wins"] += 1; away["losses"] += 1
        elif game.away_score > game.home_score:
            away["wins"] += 1; home["losses"] += 1
        else:
            home["ties"] += 1; away["ties"] += 1

    for row in rows.values():
        games = row["games"]
        row["pct"] = round((row["wins"] + 0.5 * row["ties"]) / games, 3) if games else 0
        row["run_diff"] = row["runs_for"] - row["runs_against"]
        row["run_diff_per_game"] = round(row["run_diff"] / games, 2) if games else 0

    for row in rows.values():
        opp_pcts = [rows[team_id]["pct"] for team_id in row["opponents"] if team_id in rows]
        row["strength_of_schedule"] = round(sum(opp_pcts) / len(opp_pcts), 3) if opp_pcts else 0
        diff_norm = max(0, min(1, 0.5 + row["run_diff_per_game"] / 20))
        row["power_score"] = round(100 * (0.55 * row["pct"] + 0.25 * diff_norm + 0.20 * row["strength_of_schedule"]), 1)
        row.pop("opponents", None)

    ordered = sorted(
        rows.values(),
        key=lambda row: (-row["pct"], -row["run_diff"], -row["runs_for"], row["team"]["group_name"].lower()),
    )
    for index, row in enumerate(ordered, start=1):
        row["standing_rank"] = index
    power = sorted(ordered, key=lambda row: (-row["power_score"], -row["pct"], -row["run_diff"]))
    for index, row in enumerate(power, start=1):
        row["power_rank"] = index
    return ordered


def division_team_stats(division):
    standings = {row["team"]["id"]: row for row in division_standings(division)}
    game_links = list(
        LeagueGame.objects.filter(division=division, source=LeagueGame.Source.LEAGUE)
        .select_related("home_team", "away_team")
    )
    team_game_ids = {}
    for game in game_links:
        if game.home_sports_game_id:
            team_game_ids.setdefault(game.home_team_id, []).append(game.home_sports_game_id)
        if game.away_sports_game_id:
            team_game_ids.setdefault(game.away_team_id, []).append(game.away_sports_game_id)

    teams = []
    player_leaders = []
    for entry in LeagueTeamEntry.objects.filter(division=division, status=LeagueTeamEntry.Status.ACTIVE).select_related("team__group"):
        team = entry.team
        game_ids = team_game_ids.get(team.id, [])
        appearances = list(
            SoftballPlateAppearance.objects.filter(game_id__in=game_ids)
            .select_related("player", "game")
        )
        ab = hits = walks = sf = tb = hr = rbi = 0
        player_rows = {}
        for pa in appearances:
            prow = player_rows.setdefault(pa.player_id, {"player": pa.player, "pa": 0, "ab": 0, "h": 0, "bb": 0, "sf": 0, "tb": 0, "hr": 0, "rbi": 0})
            prow["pa"] += 1; prow["rbi"] += pa.rbi
            rbi += pa.rbi
            if pa.result not in AB_EXCLUDED_RESULTS:
                ab += 1; prow["ab"] += 1
            if pa.result in HIT_RESULTS:
                hits += 1; prow["h"] += 1
            if pa.result == SoftballPlateAppearance.Result.WALK:
                walks += 1; prow["bb"] += 1
            elif pa.result == SoftballPlateAppearance.Result.SAC_FLY:
                sf += 1; prow["sf"] += 1
            elif pa.result == SoftballPlateAppearance.Result.SINGLE:
                tb += 1; prow["tb"] += 1
            elif pa.result == SoftballPlateAppearance.Result.DOUBLE:
                tb += 2; prow["tb"] += 2
            elif pa.result == SoftballPlateAppearance.Result.TRIPLE:
                tb += 3; prow["tb"] += 3
            elif pa.result == SoftballPlateAppearance.Result.HOME_RUN:
                tb += 4; hr += 1; prow["tb"] += 4; prow["hr"] += 1
        avg = round(hits / ab, 3) if ab else 0
        obp = round((hits + walks) / (ab + walks + sf), 3) if (ab + walks + sf) else 0
        slg = round(tb / ab, 3) if ab else 0
        standing = standings.get(team.id, {})
        teams.append({
            "team": SportsTeamSerializer(team).data,
            "g": standing.get("games", 0),
            "avg": avg, "obp": obp, "slg": slg, "ops": round(obp + slg, 3),
            "h": hits, "hr": hr, "rbi": rbi,
            "runs_for": standing.get("runs_for", 0),
            "runs_against": standing.get("runs_against", 0),
            "runs_per_game": round(standing.get("runs_for", 0) / standing.get("games", 1), 2) if standing.get("games") else 0,
        })
        for prow in player_rows.values():
            pab = prow["ab"]; ph = prow["h"]; pbb = prow["bb"]; psf = prow["sf"]
            pobp = (ph + pbb) / (pab + pbb + psf) if (pab + pbb + psf) else 0
            pslg = prow["tb"] / pab if pab else 0
            player_leaders.append({
                "team_id": team.id,
                "team_name": team.group.name,
                "player": SportsPlayerSerializer(prow["player"]).data,
                "pa": prow["pa"], "avg": round(ph / pab, 3) if pab else 0,
                "ops": round(pobp + pslg, 3), "hr": prow["hr"], "rbi": prow["rbi"],
            })
    return {
        "teams": sorted(teams, key=lambda row: (-row["ops"], -row["avg"], row["team"]["group_name"].lower())),
        "leaders": {
            "ops": sorted(player_leaders, key=lambda row: (-row["ops"], -row["pa"]))[:10],
            "avg": sorted(player_leaders, key=lambda row: (-row["avg"], -row["pa"]))[:10],
            "hr": sorted(player_leaders, key=lambda row: (-row["hr"], -row["pa"]))[:10],
            "rbi": sorted(player_leaders, key=lambda row: (-row["rbi"], -row["pa"]))[:10],
        },
    }


class SportsOrganizationViewSet(viewsets.ModelViewSet):
    serializer_class = SportsOrganizationSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        return SportsOrganization.objects.filter(
            Q(is_public=True)
            | Q(memberships__user=self.request.user, memberships__status=SportsOrganizationMembership.Status.ACTIVE)
        ).distinct().prefetch_related("memberships", "seasons")

    @transaction.atomic
    def perform_create(self, serializer):
        name = serializer.validated_data["name"]
        if not serializer.validated_data.get("slug"):
            serializer.validated_data["slug"] = unique_org_slug(name)
        organization = serializer.save(created_by=self.request.user)
        SportsOrganizationMembership.objects.create(
            organization=organization,
            user=self.request.user,
            role=SportsOrganizationMembership.Role.COMMISSIONER,
            status=SportsOrganizationMembership.Status.ACTIVE,
            invited_by=self.request.user,
        )

    def perform_update(self, serializer):
        organization = self.get_object()
        if not can_manage_organization(self.request.user, organization):
            raise serializers.ValidationError("Commissioner or league admin access is required.")
        serializer.save()

    @action(detail=True, methods=["get"])
    def dashboard(self, request, pk=None):
        organization = self.get_object()
        seasons = organization.seasons.prefetch_related("divisions__team_entries", "divisions__roster_entries")
        current = seasons.filter(is_current=True).first() or seasons.filter(status=LeagueSeason.Status.ACTIVE).first()
        divisions = current.divisions.all() if current else LeagueDivision.objects.none()
        return Response({
            "organization": self.get_serializer(organization).data,
            "current_season": LeagueSeasonSerializer(current).data if current else None,
            "divisions": LeagueDivisionSerializer(divisions, many=True).data,
            "team_count": LeagueTeamEntry.objects.filter(division__season__organization=organization, status=LeagueTeamEntry.Status.ACTIVE).values("team_id").distinct().count(),
            "active_roster_count": LeagueRosterEntry.objects.filter(division__season__organization=organization, status=LeagueRosterEntry.Status.ACTIVE).count(),
            "scheduled_game_count": LeagueGame.objects.filter(division__season__organization=organization).exclude(status=LeagueGame.Status.CANCELLED).count(),
            "tournament_count": LeagueTournament.objects.filter(organization=organization).exclude(status=LeagueTournament.Status.CANCELLED).count(),
            "can_manage": can_manage_organization(request.user, organization),
        })

    @action(detail=True, methods=["get"], url_path="available-teams")
    def available_teams(self, request, pk=None):
        organization = self.get_object()
        if not can_manage_organization(request.user, organization):
            return Response({"detail": "Commissioner or league admin access is required."}, status=status.HTTP_403_FORBIDDEN)
        group_ids = GroupMembership.objects.filter(
            user=request.user,
            status=GroupMembership.Status.ACTIVE,
        ).values_list("group_id", flat=True)
        teams = SportsTeam.objects.filter(
            sport=organization.sport,
        ).filter(
            Q(group_id__in=group_ids) | Q(group__visibility="PUBLIC")
        ).select_related("group").distinct().order_by("group__name")
        return Response(SportsTeamSerializer(teams, many=True).data)


class SportsOrganizationMembershipViewSet(viewsets.ModelViewSet):
    serializer_class = SportsOrganizationMembershipSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        return SportsOrganizationMembership.objects.filter(
            Q(user=self.request.user)
            | Q(organization__memberships__user=self.request.user,
                organization__memberships__status=SportsOrganizationMembership.Status.ACTIVE,
                organization__memberships__role__in=ORG_MANAGEMENT_ROLES)
        ).select_related("organization", "user", "invited_by").distinct()

    def perform_create(self, serializer):
        organization = serializer.validated_data["organization"]
        if not can_manage_organization(self.request.user, organization):
            raise serializers.ValidationError("Commissioner or league admin access is required.")
        serializer.save(invited_by=self.request.user)

    def perform_update(self, serializer):
        membership = self.get_object()
        if not can_manage_organization(self.request.user, membership.organization):
            raise serializers.ValidationError("Commissioner or league admin access is required.")
        serializer.save()


class LeagueSeasonViewSet(viewsets.ModelViewSet):
    serializer_class = LeagueSeasonSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = LeagueSeason.objects.filter(
            Q(organization__is_public=True)
            | Q(organization__memberships__user=self.request.user, organization__memberships__status=SportsOrganizationMembership.Status.ACTIVE)
        ).select_related("organization", "created_by").prefetch_related("divisions").distinct()
        organization_id = self.request.query_params.get("organization")
        return queryset.filter(organization_id=organization_id) if organization_id else queryset

    @transaction.atomic
    def perform_create(self, serializer):
        organization = serializer.validated_data["organization"]
        if not can_manage_organization(self.request.user, organization):
            raise serializers.ValidationError("Commissioner or league admin access is required.")
        if serializer.validated_data.get("is_current"):
            organization.seasons.update(is_current=False)
        serializer.save(created_by=self.request.user)

    @transaction.atomic
    def perform_update(self, serializer):
        season = self.get_object()
        if not can_manage_organization(self.request.user, season.organization):
            raise serializers.ValidationError("Commissioner or league admin access is required.")
        if serializer.validated_data.get("is_current"):
            season.organization.seasons.exclude(pk=season.pk).update(is_current=False)
        serializer.save()


class LeagueDivisionViewSet(viewsets.ModelViewSet):
    serializer_class = LeagueDivisionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = LeagueDivision.objects.filter(
            Q(season__organization__is_public=True)
            | Q(season__organization__memberships__user=self.request.user,
                season__organization__memberships__status=SportsOrganizationMembership.Status.ACTIVE)
        ).select_related("season__organization").prefetch_related("team_entries", "roster_entries").distinct()
        season_id = self.request.query_params.get("season")
        return queryset.filter(season_id=season_id) if season_id else queryset

    def perform_create(self, serializer):
        season = serializer.validated_data["season"]
        if not can_manage_organization(self.request.user, season.organization):
            raise serializers.ValidationError("Commissioner or league admin access is required.")
        serializer.save()

    def perform_update(self, serializer):
        division = self.get_object()
        if not can_manage_division(self.request.user, division):
            raise serializers.ValidationError("Commissioner or league admin access is required.")
        if "season" in serializer.validated_data and serializer.validated_data["season"].organization_id != division.season.organization_id:
            raise serializers.ValidationError({"season": "Division cannot be moved to another organization."})
        serializer.save()


    @action(detail=True, methods=["get"], url_path="standings")
    def standings(self, request, pk=None):
        division = self.get_object()
        rows = division_standings(division)
        return Response({
            "division": LeagueDivisionSerializer(division).data,
            "standings": rows,
            "power_formula": "55% win pct + 25% normalized run differential/game + 20% strength of schedule",
        })

    @action(detail=True, methods=["get"], url_path="league-stats")
    def league_stats(self, request, pk=None):
        division = self.get_object()
        return Response(division_team_stats(division))

    @action(detail=True, methods=["post"], url_path="build-schedule")
    @transaction.atomic
    def build_schedule(self, request, pk=None):
        division = self.get_object()
        if not can_manage_division(request.user, division):
            return Response({"detail": "Commissioner or league admin access is required."}, status=status.HTTP_403_FORBIDDEN)
        if LeagueGame.objects.filter(division=division, source=LeagueGame.Source.LEAGUE).exclude(status=LeagueGame.Status.CANCELLED).exists():
            return Response({"detail": "This division already has a league schedule. Edit the existing schedule instead of generating duplicates."}, status=status.HTTP_409_CONFLICT)

        entries = list(
            LeagueTeamEntry.objects.filter(division=division, status=LeagueTeamEntry.Status.ACTIVE)
            .select_related("team__group").order_by("seed", "team__group__name")
        )
        sports_teams = [entry.team for entry in entries]
        if len(sports_teams) < 2:
            return Response({"detail": "Add at least two active teams before building a schedule."}, status=status.HTTP_400_BAD_REQUEST)
        start_at = _aware_datetime(request.data.get("start_at"))
        if not start_at:
            return Response({"detail": "start_at must be an ISO date/time."}, status=status.HTTP_400_BAD_REQUEST)

        fields = request.data.get("fields") or []
        if isinstance(fields, str):
            fields = [value.strip() for value in fields.split(",") if value.strip()]
        fields = list(fields) or [str(request.data.get("field_name") or "Field TBD")]
        slot_minutes = max(30, int(request.data.get("slot_minutes") or 60))
        days_between_rounds = max(1, int(request.data.get("days_between_rounds") or 7))
        games_per_matchup = min(4, max(1, int(request.data.get("games_per_matchup") or 1)))

        generated = []
        base_rounds = round_robin_rounds(sports_teams)
        round_number = 0
        for cycle in range(games_per_matchup):
            for pairs in base_rounds:
                round_number += 1
                round_start = start_at + timedelta(days=(round_number - 1) * days_between_rounds)
                for index, (first, second) in enumerate(pairs):
                    home, away = (second, first) if cycle % 2 else (first, second)
                    field_name = fields[index % len(fields)]
                    slot_index = index // len(fields)
                    game_start = round_start + timedelta(minutes=slot_index * slot_minutes)
                    payload = dict(request.data)
                    payload["field_name"] = field_name
                    game = _build_game(
                        division, home, away, request.user, game_start, payload,
                        source=LeagueGame.Source.LEAGUE,
                        week_number=round_number,
                    )
                    generated.append(game)

        return Response({
            "created": len(generated),
            "games": LeagueGameSerializer(generated, many=True).data,
        }, status=status.HTTP_201_CREATED)


class LeagueTeamEntryViewSet(viewsets.ModelViewSet):
    serializer_class = LeagueTeamEntrySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = LeagueTeamEntry.objects.filter(
            Q(division__season__organization__is_public=True)
            | Q(division__season__organization__memberships__user=self.request.user,
                division__season__organization__memberships__status=SportsOrganizationMembership.Status.ACTIVE)
            | Q(team__group__memberships__user=self.request.user, team__group__memberships__status=GroupMembership.Status.ACTIVE)
        ).select_related("division__season__organization", "team__group").distinct()
        division_id = self.request.query_params.get("division")
        return queryset.filter(division_id=division_id) if division_id else queryset

    def perform_create(self, serializer):
        division = serializer.validated_data["division"]
        if not can_manage_division(self.request.user, division):
            raise serializers.ValidationError("Commissioner or league admin access is required to add teams.")
        entry = serializer.save()
        entry.full_clean()

    def perform_update(self, serializer):
        entry = self.get_object()
        if not can_manage_division(self.request.user, entry.division):
            raise serializers.ValidationError("Commissioner or league admin access is required.")
        serializer.save()


class LeagueRosterEntryViewSet(viewsets.ModelViewSet):
    serializer_class = LeagueRosterEntrySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = LeagueRosterEntry.objects.filter(
            Q(division__season__organization__is_public=True)
            | Q(division__season__organization__memberships__user=self.request.user,
                division__season__organization__memberships__status=SportsOrganizationMembership.Status.ACTIVE)
            | Q(team__group__memberships__user=self.request.user, team__group__memberships__status=GroupMembership.Status.ACTIVE)
            | Q(identity__user=self.request.user)
        ).select_related("division__season__organization", "team__group", "identity__user", "sports_player").distinct()
        division_id = self.request.query_params.get("division")
        team_id = self.request.query_params.get("team")
        if division_id:
            queryset = queryset.filter(division_id=division_id)
        if team_id:
            queryset = queryset.filter(team_id=team_id)
        return queryset

    def _can_manage_roster(self, user, division, team):
        return can_manage_division(user, division) or can_manage_team(user, team)

    @action(detail=False, methods=["post"], url_path="invite-email")
    @transaction.atomic
    def invite_email(self, request):
        division = get_object_or_404(LeagueDivision.objects.select_related("season__organization"), pk=request.data.get("division"))
        team_entry = get_object_or_404(
            LeagueTeamEntry.objects.select_related("team__group"),
            division=division,
            team_id=request.data.get("team"),
            status=LeagueTeamEntry.Status.ACTIVE,
        )
        team = team_entry.team
        if not self._can_manage_roster(request.user, division, team):
            return Response({"detail": "League admin or team manager access is required."}, status=status.HTTP_403_FORBIDDEN)

        email = str(request.data.get("email") or "").strip().lower()
        if not email or "@" not in email:
            return Response({"email": "Enter a valid player email."}, status=status.HTTP_400_BAD_REQUEST)
        display_name = str(request.data.get("display_name") or "").strip()
        jersey_number = str(request.data.get("jersey_number") or "").strip()

        if division.max_roster_size:
            current = LeagueRosterEntry.objects.filter(
                division=division,
                team=team,
                status__in=(LeagueRosterEntry.Status.INVITED, LeagueRosterEntry.Status.ACTIVE),
            ).count()
            existing = LeagueRosterEntry.objects.filter(division=division, team=team, identity__email=email).exists()
            if current >= division.max_roster_size and not existing:
                return Response({"detail": f"Roster limit of {division.max_roster_size} has been reached."}, status=status.HTTP_400_BAD_REQUEST)

        identity, _ = SportsPlayerIdentity.objects.get_or_create(
            email=email,
            defaults={"display_name": display_name},
        )
        if display_name and not identity.display_name:
            identity.display_name = display_name
            identity.save(update_fields=("display_name", "updated_at"))

        matched_user = User.objects.filter(email__iexact=email).first()
        if matched_user and not identity.user_id:
            identity.claim(matched_user)

        player = None
        if identity.user_id:
            player, _ = SportsPlayer.objects.get_or_create(
                team=team,
                user=identity.user,
                defaults={
                    "display_name": identity.display_name or identity.email,
                    "jersey_number": jersey_number,
                    "created_by": request.user,
                },
            )
            GroupMembership.objects.update_or_create(
                group=team.group,
                user=identity.user,
                defaults={
                    "role": GroupMembership.Role.MEMBER,
                    "status": GroupMembership.Status.ACTIVE,
                    "invited_by": request.user,
                },
            )

        roster, created = LeagueRosterEntry.objects.get_or_create(
            division=division,
            team=team,
            identity=identity,
            defaults={
                "sports_player": player,
                "jersey_number": jersey_number,
                "status": LeagueRosterEntry.Status.ACTIVE if identity.user_id else LeagueRosterEntry.Status.INVITED,
                "accepted_at": timezone.now() if identity.user_id else None,
                "invited_by": request.user,
            },
        )
        if not created:
            roster.jersey_number = jersey_number or roster.jersey_number
            roster.sports_player = player or roster.sports_player
            if identity.user_id:
                roster.status = LeagueRosterEntry.Status.ACTIVE
                roster.accepted_at = roster.accepted_at or timezone.now()
            elif roster.status == LeagueRosterEntry.Status.REMOVED:
                roster.status = LeagueRosterEntry.Status.INVITED
            roster.invited_by = request.user
            roster.invited_at = timezone.now()
            roster.save()

        urls = send_roster_invite_email(roster)
        payload = self.get_serializer(roster).data
        payload.update({
            "invite_url": urls["invite_url"],
            "account_exists": bool(identity.user_id),
            "email_sent": True,
        })
        return Response(payload, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="invite-preview", permission_classes=[AllowAny])
    def invite_preview(self, request):
        token = str(request.query_params.get("token") or "").strip()
        roster_id = request.query_params.get("roster")
        identity = get_object_or_404(SportsPlayerIdentity, claim_token=token)
        roster_qs = identity.roster_entries.select_related(
            "team__group", "division__season__organization"
        ).exclude(status=LeagueRosterEntry.Status.REMOVED)
        if roster_id:
            roster_qs = roster_qs.filter(pk=roster_id)
        roster = roster_qs.first()
        if not roster:
            return Response({"detail": "This team invitation is no longer active."}, status=status.HTTP_404_NOT_FOUND)
        email = identity.email
        local, _, domain = email.partition("@")
        masked = (local[:1] + "***@" + domain) if domain else "***"
        urls = _invite_urls(identity, roster)
        return Response({
            "roster": roster.id,
            "team_id": roster.team_id,
            "group_id": roster.team.group_id,
            "team_name": roster.team.group.name,
            "league_name": roster.division.season.organization.name,
            "season_name": roster.division.season.name,
            "division_name": roster.division.name,
            "player_name": identity.display_name or "",
            "email_masked": masked,
            "account_exists": bool(identity.user_id),
            "status": roster.status,
            "register_url": urls["register_url"],
            "login_url": urls["login_url"],
        })

    @action(detail=False, methods=["post"], url_path="claim-token")
    @transaction.atomic
    def claim_token(self, request):
        token = str(request.data.get("token") or "").strip()
        roster_id = request.data.get("roster")
        identity = get_object_or_404(SportsPlayerIdentity, claim_token=token)
        email = str(getattr(request.user, "email", "") or "").strip().lower()
        if not email or email != identity.email:
            return Response(
                {"detail": "Sign in with the email address that received this team invitation."},
                status=status.HTTP_403_FORBIDDEN,
            )
        roster_qs = identity.roster_entries.select_related(
            "team__group", "division__season__organization"
        ).exclude(status=LeagueRosterEntry.Status.REMOVED)
        if roster_id:
            roster_qs = roster_qs.filter(pk=roster_id)
        roster = roster_qs.first()
        if not roster:
            return Response({"detail": "This team invitation is no longer active."}, status=status.HTTP_404_NOT_FOUND)

        identity.claim(request.user)
        player, _ = SportsPlayer.objects.get_or_create(
            team=roster.team,
            user=request.user,
            defaults={
                "display_name": identity.display_name or email,
                "jersey_number": roster.jersey_number,
                "created_by": roster.invited_by or request.user,
            },
        )
        GroupMembership.objects.update_or_create(
            group=roster.team.group,
            user=request.user,
            defaults={
                "role": GroupMembership.Role.MEMBER,
                "status": GroupMembership.Status.ACTIVE,
                "invited_by": roster.invited_by,
            },
        )
        roster.sports_player = player
        roster.status = LeagueRosterEntry.Status.ACTIVE
        roster.accepted_at = roster.accepted_at or timezone.now()
        roster.save(update_fields=("sports_player", "status", "accepted_at", "updated_at"))
        return Response({
            "claimed": True,
            "team_id": roster.team_id,
            "group_id": roster.team.group_id,
            "route": f"/connect/groups/{roster.team.group_id}/sports",
            "roster": self.get_serializer(roster).data,
        })

    @action(detail=False, methods=["post"], url_path="claim-mine")
    @transaction.atomic
    def claim_mine(self, request):
        email = str(getattr(request.user, "email", "") or "").strip().lower()
        if not email:
            return Response({"detail": "Your SyncWorks account needs an email address."}, status=status.HTTP_400_BAD_REQUEST)
        identity = SportsPlayerIdentity.objects.filter(email=email).first()
        if not identity:
            return Response({"claimed": 0, "detail": "No pending sports roster invitations match this email."})
        try:
            identity.claim(request.user)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        claimed = []
        for roster in identity.roster_entries.select_related("team__group", "division").exclude(status=LeagueRosterEntry.Status.REMOVED):
            player, _ = SportsPlayer.objects.get_or_create(
                team=roster.team,
                user=request.user,
                defaults={
                    "display_name": identity.display_name or email,
                    "jersey_number": roster.jersey_number,
                    "created_by": roster.invited_by or request.user,
                },
            )
            GroupMembership.objects.update_or_create(
                group=roster.team.group,
                user=request.user,
                defaults={
                    "role": GroupMembership.Role.MEMBER,
                    "status": GroupMembership.Status.ACTIVE,
                    "invited_by": roster.invited_by,
                },
            )
            roster.sports_player = player
            roster.status = LeagueRosterEntry.Status.ACTIVE
            roster.accepted_at = roster.accepted_at or timezone.now()
            roster.save(update_fields=("sports_player", "status", "accepted_at", "updated_at"))
            claimed.append(roster)
        return Response({"claimed": len(claimed), "rosters": self.get_serializer(claimed, many=True).data})

    def perform_update(self, serializer):
        roster = self.get_object()
        if not self._can_manage_roster(self.request.user, roster.division, roster.team):
            raise serializers.ValidationError("League admin or team manager access is required.")
        serializer.save()

    def perform_destroy(self, instance):
        if not self._can_manage_roster(self.request.user, instance.division, instance.team):
            raise serializers.ValidationError("League admin or team manager access is required.")
        instance.status = LeagueRosterEntry.Status.REMOVED
        instance.save(update_fields=("status", "updated_at"))


class LeagueGameViewSet(viewsets.ModelViewSet):
    serializer_class = LeagueGameSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = LeagueGame.objects.filter(
            Q(division__season__organization__is_public=True)
            | Q(
                division__season__organization__memberships__user=self.request.user,
                division__season__organization__memberships__status=SportsOrganizationMembership.Status.ACTIVE,
            )
            | Q(home_team__group__memberships__user=self.request.user, home_team__group__memberships__status=GroupMembership.Status.ACTIVE)
            | Q(away_team__group__memberships__user=self.request.user, away_team__group__memberships__status=GroupMembership.Status.ACTIVE)
        ).select_related(
            "division__season__organization", "home_team__group", "away_team__group",
            "tournament", "rule_set", "home_sports_game", "away_sports_game",
        ).distinct()
        division = self.request.query_params.get("division")
        tournament = self.request.query_params.get("tournament")
        source = self.request.query_params.get("source")
        if division:
            queryset = queryset.filter(division_id=division)
        if tournament:
            queryset = queryset.filter(tournament_id=tournament)
        if source:
            queryset = queryset.filter(source=source)
        return queryset

    @transaction.atomic
    def perform_create(self, serializer):
        division = serializer.validated_data["division"]
        if not can_manage_division(self.request.user, division):
            raise serializers.ValidationError("Commissioner or league admin access is required.")
        game = serializer.save(created_by=self.request.user)
        game.full_clean()
        create_league_game_records(game, self.request.user)

    @transaction.atomic
    def perform_update(self, serializer):
        game = self.get_object()
        if not can_manage_division(self.request.user, game.division):
            raise serializers.ValidationError("Commissioner or league admin access is required.")
        saved = serializer.save()
        saved.full_clean()
        sync_league_game_records(saved)

    @transaction.atomic
    def perform_destroy(self, instance):
        if not can_manage_division(self.request.user, instance.division):
            raise serializers.ValidationError("Commissioner or league admin access is required.")
        instance.status = LeagueGame.Status.CANCELLED
        instance.save(update_fields=("status", "updated_at"))
        sync_league_game_records(instance)


class LeagueTournamentViewSet(viewsets.ModelViewSet):
    serializer_class = LeagueTournamentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = LeagueTournament.objects.filter(
            Q(organization__is_public=True)
            | Q(
                organization__memberships__user=self.request.user,
                organization__memberships__status=SportsOrganizationMembership.Status.ACTIVE,
            )
        ).select_related(
            "organization", "season", "division", "rule_set", "created_by",
        ).prefetch_related("entries__team__group", "byes__team__group", "games").distinct()
        organization = self.request.query_params.get("organization")
        season = self.request.query_params.get("season")
        division = self.request.query_params.get("division")
        if organization:
            queryset = queryset.filter(organization_id=organization)
        if season:
            queryset = queryset.filter(season_id=season)
        if division:
            queryset = queryset.filter(division_id=division)
        return queryset

    def perform_create(self, serializer):
        organization = serializer.validated_data["organization"]
        if not can_manage_organization(self.request.user, organization):
            raise serializers.ValidationError("Commissioner or league admin access is required.")
        tournament = serializer.save(created_by=self.request.user)
        tournament.full_clean()

    def perform_update(self, serializer):
        tournament = self.get_object()
        if not can_manage_organization(self.request.user, tournament.organization):
            raise serializers.ValidationError("Commissioner or league admin access is required.")
        saved = serializer.save()
        saved.full_clean()

    @action(detail=True, methods=["post"], url_path="add-team")
    def add_team(self, request, pk=None):
        tournament = self.get_object()
        if not can_manage_organization(request.user, tournament.organization):
            return Response({"detail": "Commissioner or league admin access is required."}, status=status.HTTP_403_FORBIDDEN)
        team = get_object_or_404(SportsTeam.objects.select_related("group"), pk=request.data.get("team"), sport=tournament.organization.sport)
        if tournament.division_id and not LeagueTeamEntry.objects.filter(
            division=tournament.division,
            team=team,
            status=LeagueTeamEntry.Status.ACTIVE,
        ).exists():
            return Response({"detail": "Add this team to the tournament division first."}, status=status.HTTP_400_BAD_REQUEST)
        seed = request.data.get("seed")
        try:
            seed = int(seed) if seed not in (None, "") else None
        except (TypeError, ValueError):
            return Response({"detail": "Seed must be a whole number."}, status=status.HTTP_400_BAD_REQUEST)
        entry, created = LeagueTournamentEntry.objects.update_or_create(
            tournament=tournament,
            team=team,
            defaults={"seed": seed, "is_active": True},
        )
        return Response(LeagueTournamentEntrySerializer(entry).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @action(detail=True, methods=["get"])
    def bracket(self, request, pk=None):
        tournament = self.get_object()
        return Response({
            "tournament": self.get_serializer(tournament).data,
            "entries": LeagueTournamentEntrySerializer(tournament.entries.filter(is_active=True).select_related("team__group"), many=True).data,
            "byes": LeagueTournamentByeSerializer(tournament.byes.select_related("team__group"), many=True).data,
            "games": LeagueGameSerializer(tournament.games.select_related("home_team__group", "away_team__group", "rule_set"), many=True).data,
        })

    @action(detail=True, methods=["post"], url_path="build")
    @transaction.atomic
    def build(self, request, pk=None):
        tournament = self.get_object()
        if not can_manage_organization(request.user, tournament.organization):
            return Response({"detail": "Commissioner or league admin access is required."}, status=status.HTTP_403_FORBIDDEN)
        if not tournament.division_id:
            return Response({"detail": "Choose a division before building the tournament."}, status=status.HTTP_400_BAD_REQUEST)
        if tournament.games.exclude(status=LeagueGame.Status.CANCELLED).exists():
            return Response({"detail": "This tournament already has a bracket/schedule."}, status=status.HTTP_409_CONFLICT)
        entries = list(tournament.entries.filter(is_active=True).select_related("team__group").order_by("seed", "team__group__name"))
        if len(entries) < 2:
            return Response({"detail": "Add at least two teams to the tournament."}, status=status.HTTP_400_BAD_REQUEST)
        start_at = _aware_datetime(request.data.get("start_at"))
        if not start_at:
            return Response({"detail": "start_at must be an ISO date/time."}, status=status.HTTP_400_BAD_REQUEST)
        fields = request.data.get("fields") or []
        if isinstance(fields, str):
            fields = [value.strip() for value in fields.split(",") if value.strip()]
        fields = list(fields) or [str(request.data.get("field_name") or "Field TBD")]
        slot_minutes = max(30, int(request.data.get("slot_minutes") or 60))
        payload = dict(request.data)
        payload.setdefault("venue_name", tournament.venue_name)
        payload.setdefault("address_line1", tournament.address_line1)
        payload.setdefault("city", tournament.city)
        payload.setdefault("state", tournament.state)
        generated = []

        if tournament.format == LeagueTournament.Format.ROUND_ROBIN:
            rounds = round_robin_rounds([entry.team for entry in entries])
            for round_index, pairs in enumerate(rounds, start=1):
                round_start = start_at + timedelta(days=round_index - 1)
                for index, (home, away) in enumerate(pairs):
                    payload["field_name"] = fields[index % len(fields)]
                    game_start = round_start + timedelta(minutes=(index // len(fields)) * slot_minutes)
                    generated.append(_build_game(
                        tournament.division, home, away, request.user, game_start, payload,
                        source=LeagueGame.Source.TOURNAMENT, tournament=tournament,
                        round_number=round_index, bracket_slot=index + 1,
                    ))
        else:
            teams = [entry.team for entry in entries]
            if len(teams) % 2:
                bye_team = teams.pop(0)
                LeagueTournamentBye.objects.create(tournament=tournament, round_number=1, team=bye_team)
            pairs = []
            while teams:
                pairs.append((teams.pop(0), teams.pop(-1)))
            for index, (home, away) in enumerate(pairs):
                payload["field_name"] = fields[index % len(fields)]
                game_start = start_at + timedelta(minutes=(index // len(fields)) * slot_minutes)
                generated.append(_build_game(
                    tournament.division, home, away, request.user, game_start, payload,
                    source=LeagueGame.Source.TOURNAMENT, tournament=tournament,
                    round_number=1, bracket_slot=index + 1,
                ))

        tournament.status = LeagueTournament.Status.ACTIVE
        tournament.save(update_fields=("status", "updated_at"))
        return Response({
            "created": len(generated),
            "bracket": self.bracket(request, pk=pk).data,
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="advance")
    @transaction.atomic
    def advance(self, request, pk=None):
        tournament = self.get_object()
        if tournament.format != LeagueTournament.Format.SINGLE_ELIM:
            return Response({"detail": "Advance is only used for single-elimination brackets."}, status=status.HTTP_400_BAD_REQUEST)
        if not can_manage_organization(request.user, tournament.organization):
            return Response({"detail": "Commissioner or league admin access is required."}, status=status.HTTP_403_FORBIDDEN)
        games = list(tournament.games.exclude(status=LeagueGame.Status.CANCELLED).order_by("round_number", "bracket_slot"))
        if not games:
            return Response({"detail": "Build the tournament first."}, status=status.HTTP_400_BAD_REQUEST)
        current_round = max(int(game.round_number or 1) for game in games)
        if tournament.games.filter(round_number=current_round).exclude(status=LeagueGame.Status.FINAL).exists():
            return Response({"detail": "Finish every game in the current round before advancing."}, status=status.HTTP_409_CONFLICT)
        if tournament.games.filter(round_number=current_round + 1).exists() or tournament.byes.filter(round_number=current_round + 1).exists():
            return Response({"detail": "The next round is already built."}, status=status.HTTP_409_CONFLICT)

        eligible = []
        for game in tournament.games.filter(round_number=current_round, status=LeagueGame.Status.FINAL):
            if game.home_score == game.away_score:
                return Response({"detail": "Tournament games must have a winner before advancing."}, status=status.HTTP_409_CONFLICT)
            eligible.append(game.home_team if game.home_score > game.away_score else game.away_team)
        eligible.extend(bye.team for bye in tournament.byes.filter(round_number=current_round).select_related("team"))

        unique = {team.id: team for team in eligible}
        eligible = list(unique.values())
        if len(eligible) == 1:
            tournament.status = LeagueTournament.Status.COMPLETE
            tournament.save(update_fields=("status", "updated_at"))
            return Response({"complete": True, "champion": SportsTeamSerializer(eligible[0]).data})

        seed_map = {
            entry.team_id: (entry.seed if entry.seed is not None else 9999)
            for entry in tournament.entries.filter(is_active=True)
        }
        eligible.sort(key=lambda team: (seed_map.get(team.id, 9999), team.group.name.lower()))
        next_round = current_round + 1
        if len(eligible) % 2:
            bye_team = eligible.pop(0)
            LeagueTournamentBye.objects.create(tournament=tournament, round_number=next_round, team=bye_team)

        start_at = _aware_datetime(request.data.get("start_at"))
        if not start_at:
            latest = max(game.start_at for game in games if int(game.round_number or 1) == current_round)
            start_at = latest + timedelta(minutes=max(30, int(request.data.get("slot_minutes") or 60)))
        fields = request.data.get("fields") or []
        if isinstance(fields, str):
            fields = [value.strip() for value in fields.split(",") if value.strip()]
        fields = list(fields) or ["Field TBD"]
        slot_minutes = max(30, int(request.data.get("slot_minutes") or 60))
        payload = dict(request.data)
        payload.setdefault("venue_name", tournament.venue_name)
        payload.setdefault("address_line1", tournament.address_line1)
        payload.setdefault("city", tournament.city)
        payload.setdefault("state", tournament.state)

        created = []
        pairs = []
        while eligible:
            pairs.append((eligible.pop(0), eligible.pop(-1)))
        for index, (home, away) in enumerate(pairs):
            payload["field_name"] = fields[index % len(fields)]
            game_start = start_at + timedelta(minutes=(index // len(fields)) * slot_minutes)
            created.append(_build_game(
                tournament.division, home, away, request.user, game_start, payload,
                source=LeagueGame.Source.TOURNAMENT, tournament=tournament,
                round_number=next_round, bracket_slot=index + 1,
            ))
        return Response({
            "created": len(created),
            "bracket": self.bracket(request, pk=pk).data,
        }, status=status.HTTP_201_CREATED)



class SoftballRuleSetViewSet(viewsets.ModelViewSet):
    serializer_class = SoftballRuleSetSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = SoftballRuleSet.objects.filter(
            Q(organization__is_public=True)
            | Q(
                organization__memberships__user=self.request.user,
                organization__memberships__status=SportsOrganizationMembership.Status.ACTIVE,
            )
        ).select_related("organization", "season", "division", "created_by").distinct()
        organization_id = self.request.query_params.get("organization")
        season_id = self.request.query_params.get("season")
        division_id = self.request.query_params.get("division")
        competition_type = self.request.query_params.get("competition_type")
        if organization_id:
            queryset = queryset.filter(organization_id=organization_id)
        if season_id:
            queryset = queryset.filter(Q(season_id=season_id) | Q(season__isnull=True))
        if division_id:
            queryset = queryset.filter(Q(division_id=division_id) | Q(division__isnull=True))
        if competition_type:
            queryset = queryset.filter(competition_type=competition_type)
        return queryset

    def perform_create(self, serializer):
        organization = serializer.validated_data["organization"]
        if not can_manage_organization(self.request.user, organization):
            raise serializers.ValidationError("Commissioner or league admin access is required.")
        rules = serializer.save(created_by=self.request.user)
        rules.full_clean()

    def perform_update(self, serializer):
        rules = self.get_object()
        if not can_manage_organization(self.request.user, rules.organization):
            raise serializers.ValidationError("Commissioner or league admin access is required.")
        saved = serializer.save()
        saved.full_clean()


class SportsPlayerIdentityViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = SportsPlayerIdentitySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return SportsPlayerIdentity.objects.filter(
            Q(user=self.request.user)
            | Q(roster_entries__team__group__memberships__user=self.request.user,
                roster_entries__team__group__memberships__status=GroupMembership.Status.ACTIVE)
            | Q(roster_entries__division__season__organization__memberships__user=self.request.user,
                roster_entries__division__season__organization__memberships__status=SportsOrganizationMembership.Status.ACTIVE)
        ).select_related("user").distinct()
