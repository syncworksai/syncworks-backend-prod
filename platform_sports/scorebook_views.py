"""Private scorebook images and coach-verified historical transcription.

A photo is evidence, not a statistical event. This API intentionally never guesses
at-bats, runs or identities from image pixels.
"""
import hashlib
import json
from io import BytesIO

from django.db import transaction
from django.db.models import Max
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from platform_social.models import GroupMembership
from .models import (
    SoftballPlateAppearance, SportsGame, SportsGameInning, SportsLineupSpot,
    SportsPlayer, SportsScorebookPage, SportsScorebookReview, SportsSubstitution,
)

EDITOR_ROLES = (
    GroupMembership.Role.OWNER, GroupMembership.Role.DIRECTOR,
    GroupMembership.Role.MANAGER, GroupMembership.Role.SCOREKEEPER,
)
APPROVER_ROLES = EDITOR_ROLES[:3]
PHOTO_MAX_BYTES = 12 * 1024 * 1024
PHOTO_MAX_PIXELS = 28_000_000
MAX_PAGES_PER_GAME = 20
VALID_RESULTS = set(SoftballPlateAppearance.Result.values)


def _scorebook_member(user, game, roles=None):
    query = GroupMembership.objects.filter(
        group_id=game.team.group_id, user=user,
        status=GroupMembership.Status.ACTIVE,
    )
    if roles:
        query = query.filter(role__in=roles)
    return query.exists()


def _page_summary(page):
    return {
        "id": page.id, "side": page.side, "page_order": page.page_order,
        "filename": page.filename, "rotation": page.rotation,
        "uploaded_at": page.created_at, "sha256": page.source_sha256,
    }


def _validated_innings(payload):
    rows = payload.get("innings")
    if not isinstance(rows, list) or not (1 <= len(rows) <= 10):
        raise ValueError("Enter 1–10 innings, including each team's runs.")
    output = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Each inning needs its own score.")
        try:
            inning = int(row["inning"])
            team = int(row["team_runs"])
            opponent = int(row["opponent_runs"])
        except (TypeError, ValueError, KeyError):
            raise ValueError("Every inning needs a valid number and both run totals.")
        if inning != len(output) + 1 or inning in seen or not 0 <= team <= 99 or not 0 <= opponent <= 99:
            raise ValueError("Innings must be sequential and scores must be 0–99.")
        output.append((inning, team, opponent))
        seen.add(inning)
    return output


def _validated_plays(game, payload, innings):
    """Require identity for every PA; a batting slot alone is never a player."""
    starters = payload.get("lineup")
    entries = payload.get("plays")
    changes = payload.get("substitutions", [])
    if not isinstance(starters, list) or not starters or len(starters) > 25:
        raise ValueError("Confirm a starting batting order before approving player stats.")
    if not isinstance(entries, list) or not entries or len(entries) > 250:
        raise ValueError("Enter each plate appearance in chronological order (max 250).")
    if not isinstance(changes, list) or len(changes) > 35:
        raise ValueError("Invalid substitution history.")
    player_ids = set()
    starting_slots = {}
    for row in starters:
        try:
            slot = int(row["batting_order"])
            player_id = int(row["player"])
        except (TypeError, ValueError, KeyError):
            raise ValueError("Starting order requires a real roster player and batting slot.")
        if slot < 1 or slot > 25 or slot in starting_slots or player_id in player_ids:
            raise ValueError("Starting order has duplicate players or batting slots.")
        starting_slots[slot] = player_id
        player_ids.add(player_id)
    events = []
    for row in changes:
        try:
            seq = int(row["after_sequence"])
            slot = int(row["batting_order"])
            incoming = int(row["incoming_player"])
        except (TypeError, ValueError, KeyError):
            raise ValueError("Each substitution needs a slot, player and preceding play number.")
        if seq < 0 or seq > len(entries) or slot not in starting_slots:
            raise ValueError("Substitution references an invalid batting slot or play number.")
        events.append((seq, slot, incoming))
        player_ids.add(incoming)
    events.sort()
    active = dict(starting_slots)
    reviewed = []
    event_index = 0
    inning_plays = {inning: {"runs": 0, "outs": 0} for inning, _, _ in innings}
    for i, row in enumerate(entries, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"Play {i} must be a completed result.")
        while event_index < len(events) and events[event_index][0] < i:
            _, slot, incoming = events[event_index]
            if incoming in active.values() and active.get(slot) != incoming:
                raise ValueError("A substitute cannot occupy two batting slots.")
            active[slot] = incoming
            event_index += 1
        try:
            slot = int(row["batting_order"])
            player_id = int(row["player"])
            inning = int(row["inning"])
            result = str(row["result"]).upper()
            outs = int(row.get("outs_recorded", 0))
            rbi = int(row.get("rbi", 0))
            runs = int(row.get("runs_scored", 0))
        except (TypeError, ValueError, KeyError):
            raise ValueError(f"Play {i} needs a roster player, slot, inning and result.")
        if slot not in active or active[slot] != player_id:
            raise ValueError(f"Play {i}: player does not match batting slot #{slot}; record a substitution first.")
        if result not in VALID_RESULTS or inning not in inning_plays:
            raise ValueError(f"Play {i}: unknown result or inning.")
        if not 0 <= outs <= 3 or not 0 <= rbi <= 4 or not 0 <= runs <= 4 or rbi > runs:
            raise ValueError(f"Play {i}: check outs, RBI and runs.")
        if reviewed and inning < reviewed[-1]["inning"]:
            raise ValueError("Plays must be entered in chronological inning order.")
        notes = str(row.get("notes") or "").strip()[:240]
        inning_plays[inning]["runs"] += runs
        inning_plays[inning]["outs"] += outs
        reviewed.append({
            "sequence": i, "player_id": player_id, "batting_order": slot,
            "inning": inning, "result": result, "outs_recorded": outs,
            "rbi": rbi, "runs_scored": runs, "notes": notes,
        })
        player_ids.add(player_id)
    if not SportsPlayer.objects.filter(team=game.team, id__in=player_ids, is_active=True).count() == len(player_ids):
        raise ValueError("Every hitter and substitute must be an existing active player on this team.")
    for inning, team_runs, _ in innings:
        if inning_plays[inning]["runs"] != team_runs:
            raise ValueError(f"Inning {inning}: play-by-play runs do not match the scorebook.")
        if inning_plays[inning]["outs"] > 3:
            raise ValueError(f"Inning {inning}: more than three outs recorded.")
    return starting_slots, events, reviewed


class ScorebookMixin:
    @action(detail=True, methods=["get", "post"], url_path="scorebook-pages",
            parser_classes=[MultiPartParser, FormParser, JSONParser])
    def scorebook_pages(self, request, pk=None):
        game = self.get_object()
        if not _scorebook_member(request.user, game):
            return Response({"detail": "Only team members can view private scorebooks."}, status=403)
        if request.method == "GET":
            return Response([_page_summary(page) for page in game.scorebook_pages.all()])
        if not _scorebook_member(request.user, game, EDITOR_ROLES):
            return Response({"detail": "Scorekeeping permission required."}, status=403)
        photo = request.FILES.get("photo")
        side = str(request.data.get("side") or "TEAM").upper()
        if side not in SportsScorebookPage.Side.values:
            return Response({"detail": "Choose TEAM or OPPONENT."}, status=400)
        if not photo or photo.size > PHOTO_MAX_BYTES:
            return Response({"detail": "Choose a photo smaller than 12 MB."}, status=400)
        raw = photo.read(PHOTO_MAX_BYTES + 1)
        if len(raw) > PHOTO_MAX_BYTES:
            return Response({"detail": "Photo is too large."}, status=400)
        source_sha = hashlib.sha256(raw).hexdigest()
        previous = game.scorebook_pages.filter(source_sha256=source_sha).first()
        if previous:
            return Response(_page_summary(previous), status=200)
        if game.scorebook_pages.count() >= MAX_PAGES_PER_GAME:
            return Response({"detail": "Maximum 20 pages per game."}, status=400)
        try:
            image = Image.open(BytesIO(raw))
            if image.width * image.height > PHOTO_MAX_PIXELS:
                raise ValueError("Photo dimensions are too large.")
            image = ImageOps.exif_transpose(image)
            image = image.convert("RGB")
            image.thumbnail((3600, 3600))
            encoded = BytesIO()
            image.save(encoded, format="JPEG", quality=91, optimize=True)
            photo_bytes = encoded.getvalue()
            if len(photo_bytes) > 7 * 1024 * 1024:
                encoded = BytesIO()
                image.thumbnail((3000, 3000))
                image.save(encoded, format="JPEG", quality=84, optimize=True)
                photo_bytes = encoded.getvalue()
            if len(photo_bytes) > 7 * 1024 * 1024:
                return Response({"detail": "Image remains too large after compression."}, status=400)
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            return Response({"detail": f"Invalid image: {exc}"}, status=400)
        next_order = (game.scorebook_pages.aggregate(value=Max("page_order"))["value"] or 0) + 1
        page = SportsScorebookPage.objects.create(
            game=game, side=side, page_order=next_order,
            filename=str(photo.name or "")[:160], source_sha256=source_sha,
            image_mime="image/jpeg", image_data=photo_bytes, uploaded_by=request.user,
        )
        return Response(_page_summary(page), status=201)

    @action(detail=True, methods=["get", "patch", "delete"],
            url_path=r"scorebook-pages/(?P<page_id>[0-9]+)")
    def scorebook_page(self, request, pk=None, page_id=None):
        game = self.get_object()
        if not _scorebook_member(request.user, game):
            return Response({"detail": "Team membership required."}, status=403)
        page = get_object_or_404(SportsScorebookPage, game=game, pk=page_id)
        if request.method == "GET":
            return Response(_page_summary(page))
        if not _scorebook_member(request.user, game, EDITOR_ROLES):
            return Response({"detail": "Scorekeeping permission required."}, status=403)
        if request.method == "DELETE":
            page.delete()
            return Response(status=204)
        rotation = request.data.get("rotation", page.rotation)
        side = str(request.data.get("side", page.side)).upper()
        try:
            rotation = int(rotation)
        except (TypeError, ValueError):
            return Response({"detail": "Rotation must be 0, 90, 180 or 270."}, status=400)
        if rotation not in (0, 90, 180, 270) or side not in SportsScorebookPage.Side.values:
            return Response({"detail": "Invalid page orientation or side."}, status=400)
        page.rotation = rotation
        page.side = side
        page.save(update_fields=("rotation", "side"))
        return Response(_page_summary(page))

    @action(detail=True, methods=["get"],
            url_path=r"scorebook-pages/(?P<page_id>[0-9]+)/image")
    def scorebook_image(self, request, pk=None, page_id=None):
        game = self.get_object()
        if not _scorebook_member(request.user, game):
            return Response({"detail": "Team membership required."}, status=403)
        page = get_object_or_404(SportsScorebookPage, game=game, pk=page_id)
        response = HttpResponse(bytes(page.image_data), content_type=page.image_mime)
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    @action(detail=True, methods=["get", "put"], url_path="scorebook-review")
    def scorebook_review(self, request, pk=None):
        game = self.get_object()
        if not _scorebook_member(request.user, game):
            return Response({"detail": "Team membership required."}, status=403)
        review = SportsScorebookReview.objects.filter(game=game).first()
        if request.method == "GET":
            if not review:
                return Response({
                    "status": "DRAFT", "payload": {}, "applied_sha256": "",
                    "current_sha256": "", "needs_approval": False,
                })
            canonical = json.dumps(review.payload, sort_keys=True, separators=(",", ":"))
            current_hash = hashlib.sha256(canonical.encode()).hexdigest()
            return Response({
                "status": review.status, "payload": review.payload,
                "applied_sha256": review.applied_sha256, "current_sha256": current_hash,
                "needs_approval": current_hash != review.applied_sha256,
                "verified_at": review.verified_at,
            })
        if not _scorebook_member(request.user, game, EDITOR_ROLES):
            return Response({"detail": "Scorekeeping permission required."}, status=403)
        payload = request.data.get("payload")
        if not isinstance(payload, dict):
            return Response({"detail": "Review payload must be an object."}, status=400)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if len(canonical) > 90_000:
            return Response({"detail": "Review is too large."}, status=400)
        review, _ = SportsScorebookReview.objects.get_or_create(game=game)
        review.payload = payload
        review.updated_by = request.user
        review.save(update_fields=("payload", "updated_by", "updated_at"))
        return Response({
            "status": review.status,
            "current_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
            "needs_approval": hashlib.sha256(canonical.encode()).hexdigest() != review.applied_sha256,
            "payload": review.payload,
        })

    @action(detail=True, methods=["post"], url_path="scorebook-review/confirm")
    @transaction.atomic
    def scorebook_confirm(self, request, pk=None):
        game = self.get_object()
        if not _scorebook_member(request.user, game, APPROVER_ROLES):
            return Response({"detail": "A team owner or manager must approve scanned stats."}, status=403)
        if game.status in (SportsGame.Status.LIVE, SportsGame.Status.CANCELLED):
            return Response({"detail": "Only scheduled or final games can be imported."}, status=409)
        review = SportsScorebookReview.objects.select_for_update().filter(game=game).first()
        if not review or not game.scorebook_pages.exists():
            return Response({"detail": "Upload the source photos and save a review first."}, status=400)
        if request.data.get("confirmed") is not True:
            return Response({"detail": "Explicit approval required."}, status=400)
        approve_plays = request.data.get("approve_plays") is True
        canonical = json.dumps(review.payload, sort_keys=True, separators=(",", ":"))
        current_hash = hashlib.sha256(canonical.encode()).hexdigest()
        if request.data.get("expected_sha256") != current_hash:
            return Response({"detail": "Review changed. Reload before approval."}, status=409)
        if review.applied_sha256 == current_hash and (
            review.status == SportsScorebookReview.Status.FULLY_VERIFIED
            or (not approve_plays and review.status == SportsScorebookReview.Status.SCORE_VERIFIED)
        ):
            return Response({"status": review.status, "detail": "Already imported; nothing was added twice."})
        try:
            innings = _validated_innings(review.payload)
            starters, changes, plays = _validated_plays(game, review.payload, innings) if approve_plays else (None, [], [])
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        team_total = sum(row[1] for row in innings)
        opponent_total = sum(row[2] for row in innings)
        if game.plate_appearances.exists():
            if review.status != SportsScorebookReview.Status.FULLY_VERIFIED or request.data.get("replace_existing") is not True:
                return Response({
                    "detail": "This game already has recorded plays. Replace only a previously verified scan after explicit approval.",
                }, status=409)
        if review.status == SportsScorebookReview.Status.FULLY_VERIFIED and not approve_plays:
            return Response({"detail": "Keep per-player stats intact; approve a complete corrected book instead."}, status=409)
        previous_plays = list(game.plate_appearances.values(
            "sequence", "player_id", "inning", "result", "outs_recorded", "rbi", "runs_scored", "notes",
        ))
        review.audit_log = (review.audit_log or [])[-24:] + [{
            "at": timezone.now().isoformat(), "by": request.user.pk,
            "old_status": game.status, "old_score": [game.runs_for, game.runs_against],
            "previous_plays": previous_plays,
            "photos": list(game.scorebook_pages.values_list("source_sha256", flat=True)),
            "new_sha256": current_hash, "stage": "PLAYS" if approve_plays else "SCORE",
        }]
        if approve_plays:
            game.plate_appearances.all().delete()
            game.substitutions.all().delete()
            game.lineup_spots.all().delete()
            SportsLineupSpot.objects.bulk_create([
                SportsLineupSpot(game=game, player_id=pid, batting_order=slot)
                for slot, pid in sorted(starters.items())
            ])
            active = dict(starters)
            for after_seq, slot, incoming in changes:
                outgoing = active[slot]
                if incoming == outgoing:
                    continue
                SportsSubstitution.objects.create(
                    game=game, outgoing_player_id=outgoing,
                    incoming_player_id=incoming, batting_order=slot,
                    inning=next((p["inning"] for p in plays if p["sequence"] > after_seq), innings[-1][0]),
                    note=f"Verified historical substitution after play {after_seq}",
                    created_by=request.user,
                )
                active[slot] = incoming
            for slot, player_id in active.items():
                game.lineup_spots.filter(batting_order=slot).update(player_id=player_id)
            SoftballPlateAppearance.objects.bulk_create([
                SoftballPlateAppearance(
                    game=game, player_id=entry["player_id"], sequence=entry["sequence"],
                    inning=entry["inning"], result=entry["result"],
                    outs_recorded=entry["outs_recorded"], rbi=entry["rbi"],
                    runs_scored=entry["runs_scored"], notes=entry["notes"],
                    created_by=request.user,
                ) for entry in plays
            ])
        game.inning_lines.all().delete()
        SportsGameInning.objects.bulk_create([
            SportsGameInning(game=game, inning=n, team_runs=ours, opponent_runs=theirs)
            for n, ours, theirs in innings
        ])
        game.status = SportsGame.Status.FINAL
        game.runs_for = team_total
        game.runs_against = opponent_total
        game.current_inning = innings[-1][0]
        game.outs = 0
        game.ended_at = timezone.now()
        game.save(update_fields=(
            "status", "runs_for", "runs_against", "current_inning", "outs", "ended_at", "updated_at",
        ))
        review.status = (
            SportsScorebookReview.Status.FULLY_VERIFIED if approve_plays
            else SportsScorebookReview.Status.SCORE_VERIFIED
        )
        review.applied_sha256 = current_hash
        review.verified_by = request.user
        review.verified_at = timezone.now()
        review.save(update_fields=(
            "status", "applied_sha256", "audit_log", "verified_by", "verified_at", "updated_at",
        ))
        from .views import sync_game_social_event
        sync_game_social_event(game)
        try:
            from .league_views import sync_league_result_from_sports_game
            sync_league_result_from_sports_game(game)
        except Exception:
            pass
        return Response({
            "status": review.status,
            "runs_for": game.runs_for, "runs_against": game.runs_against,
            "plate_appearance_count": len(plays) if approve_plays else len(previous_plays),
        })
