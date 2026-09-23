"""Read-only player-by-game stat evidence. Never calls a scan 'verified' without review."""
from django.db.models import Prefetch

from .models import SportsGame, SportsGameBookPhoto


HITS = {"1B", "2B", "3B", "HR"}


def player_book_audit(player):
    games = list(
        SportsGame.objects.filter(
            team_id=player.team_id, status=SportsGame.Status.FINAL
        ).prefetch_related(
            "lineup_spots", "plate_appearances",
            Prefetch("book_photos", queryset=SportsGameBookPhoto.objects.only("id", "game_id", "review_status")),
        ).order_by("start_at", "id")
    )
    rows = []
    for game in games:
        lineup = next(
            (spot for spot in game.lineup_spots.all() if spot.player_id == player.id), None
        )
        plays = [
            pa for pa in game.plate_appearances.all()
            if pa.player_id == player.id
        ]
        if not lineup and not plays:
            continue
        photos = list(game.book_photos.all())
        reviewed_sources = sum(
            p.review_status == SportsGameBookPhoto.ReviewStatus.VERIFIED
            for p in photos
        )
        if not plays:
            status = "MISSING_PLAYS"
        elif not photos:
            status = "SOURCE_NOT_UPLOADED"
        elif reviewed_sources != len(photos):
            status = "SOURCE_REVIEW_PENDING"
        else:
            status = "SOURCE_PHOTO_REVIEWED"
        rows.append({
            "game_id": game.id,
            "opponent_name": game.opponent_name,
            "start_at": game.start_at,
            "home_away": game.home_away,
            "runs_for": game.runs_for,
            "runs_against": game.runs_against,
            "batting_order": lineup.batting_order if lineup else None,
            "appearance_count": len(plays),
            "hits_recorded": sum(pa.result in HITS for pa in plays),
            "rbi_recorded": sum(int(pa.rbi or 0) for pa in plays),
            "photo_count": len(photos),
            "reviewed_photo_count": reviewed_sources,
            "status": status,
            "plays": [{
                "id": pa.id, "inning": pa.inning, "sequence": pa.sequence,
                "result": pa.result, "rbi": pa.rbi, "runs_scored": pa.runs_scored,
            } for pa in sorted(plays, key=lambda pa: pa.sequence)],
        })
    return {
        "player_id": player.id,
        "team_id": player.team_id,
        "games": rows,
        "games_needing_review": sum(row["status"] != "SOURCE_PHOTO_REVIEWED" for row in rows),
        "recorded_appearances": sum(row["appearance_count"] for row in rows),
        "missing_play_games": sum(row["status"] == "MISSING_PLAYS" for row in rows),
    }
