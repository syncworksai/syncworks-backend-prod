from datetime import datetime
from zoneinfo import ZoneInfo

from django.db import migrations


MARKER = "Imported from Church League Gold Division Fall 2026 schedule"
ADDRESS = "8700 Minnie Brown Rd"
CITY = "Montgomery"
STATE = "AL"
TZ = ZoneInfo("America/Chicago")

# date, time, field, opponent, home_away
SCHEDULE = (
    ("2026-09-15", "18:30", 1, "Freedom Church", "AWAY"),
    ("2026-09-15", "19:30", 1, "Frazer Church", "HOME"),
    ("2026-09-22", "18:30", 2, "Vaughn Forest Church", "AWAY"),
    ("2026-09-22", "19:30", 2, "Hope Hull Church", "AWAY"),
    ("2026-09-29", "18:30", 1, "Landmark Church #1", "AWAY"),
    ("2026-09-29", "19:30", 3, "Landmark Church #2", "HOME"),
    ("2026-10-13", "18:30", 3, "Frazer Church", "AWAY"),
    ("2026-10-13", "19:30", 1, "Landmark Church #1", "HOME"),
    ("2026-10-20", "18:30", 3, "Vaughn Forest Church", "HOME"),
    ("2026-10-20", "19:30", 2, "Freedom Church", "HOME"),
)


def seed_schedule(apps, schema_editor):
    # Use the current domain helper so seeded games receive the same Social event,
    # RSVP and SyncWorks Calendar behavior as games created in the UI.
    # Always use historical models during migrations. Importing the live model
    # would query fields added in later migrations (for example badge_rules)
    # before SQLite/Postgres has created those columns.
    SportsGame = apps.get_model("platform_sports", "SportsGame")
    SportsTeam = apps.get_model("platform_sports", "SportsTeam")

    team = SportsTeam.objects.filter(group__name="Bed Springs Baptist", sport="SOFTBALL").select_related("group").first()
    if not team:
        return

    for date_value, time_value, field_number, opponent, home_away in SCHEDULE:
        start_at = datetime.fromisoformat(f"{date_value}T{time_value}:00").replace(tzinfo=TZ)
        game, created = SportsGame.objects.get_or_create(
            team=team,
            opponent_name=opponent,
            start_at=start_at,
            defaults={
                "game_type": "LEAGUE",
                "home_away": home_away,
                "timezone": "America/Chicago",
                "venue_name": f"Dean Fain Park · Field {field_number}",
                "address_line1": ADDRESS,
                "city": CITY,
                "state": STATE,
                "notes": MARKER,
                "innings_scheduled": 7,
                "created_by_id": team.created_by_id,
            },
        )
        if not created:
            changed = False
            expected = {
                "game_type": "LEAGUE",
                "home_away": home_away,
                "timezone": "America/Chicago",
                "venue_name": f"Dean Fain Park · Field {field_number}",
                "address_line1": ADDRESS,
                "city": CITY,
                "state": STATE,
                "notes": MARKER,
                "innings_scheduled": 7,
            }
            for field, value in expected.items():
                if getattr(game, field) != value:
                    setattr(game, field, value)
                    changed = True
            if changed:
                game.save()
        # This historical migration only seeds the fixture. Current Sports
        # endpoints sync game schedules into Social calendars when they are
        # created or edited, after all later schema migrations are present.


def unseed_schedule(apps, schema_editor):
    PersonalCalendarEvent = apps.get_model("personal_calendar", "PersonalCalendarEvent")
    SportsGame = apps.get_model("platform_sports", "SportsGame")

    games = list(SportsGame.objects.filter(team__group__name="Bed Springs Baptist", notes=MARKER).select_related("social_event"))
    event_ids = [game.social_event_id for game in games if game.social_event_id]
    if event_ids:
        PersonalCalendarEvent.objects.filter(source="SYNC", metadata__social_event_id__in=event_ids).delete()
    for game in games:
        event = game.social_event
        game.delete()
        if event:
            event.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("platform_sports", "0003_team_manager_ops"),
    ]

    operations = [
        migrations.RunPython(seed_schedule, unseed_schedule),
    ]
