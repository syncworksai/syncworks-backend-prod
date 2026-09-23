"""Link the two approved Bed Springs accounts to existing scored roster records.

Run only when the fixture and identity guards all match; never manufacture
stats, overwrite linked accounts, or delete a historical player.
"""
from django.db import migrations, transaction
from django.db.models import Q


def link_bed_springs_accounts(apps, schema_editor):
    Player = apps.get_model("platform_sports", "SportsPlayer")
    Profile = apps.get_model("platform_sports", "SportsPlayerProfile")
    Lineup = apps.get_model("platform_sports", "SportsLineupSpot")
    PlateAppearance = apps.get_model("platform_sports", "SoftballPlateAppearance")
    StatEntry = apps.get_model("platform_sports", "SoftballStatLedgerEntry")
    Fee = apps.get_model("platform_sports", "TeamFeeAssignment")
    Award = apps.get_model("platform_sports", "SportsPlayerAward")
    Moment = apps.get_model("platform_sports", "SportsPlayerMoment")
    Substitution = apps.get_model("platform_sports", "SportsSubstitution")
    Membership = apps.get_model("platform_social", "GroupMembership")
    User = apps.get_model("user_accounts", "User")

    with transaction.atomic():
        people = {
            p.id: p
            for p in Player.objects.select_for_update().select_related("team__group")
            .filter(pk__in=(4, 5, 16), team_id=1)
        }
        if not all(pid in people for pid in (4, 5, 16)):
            return
        zack, shaw, duplicate = people[4], people[5], people[16]
        if shaw.team.group.name != "Bed Springs Baptist":
            return
        if not (
            zack.display_name.casefold() == "zack azar"
            and shaw.display_name.casefold() == "shaw aplin"
            and duplicate.display_name.casefold() == "shaw aplin"
            and zack.jersey_number == "67"
            and shaw.jersey_number == "69"
        ):
            return

        users = {u.id: u for u in User.objects.filter(pk__in=(38, 41))}
        if len(users) != 2:
            return
        zack_user, shaw_user = users[38], users[41]
        if not (
            zack_user.first_name.casefold() == "zack"
            and zack_user.last_name.casefold() == "azar"
            and shaw_user.first_name.casefold() == "shaw"
            and shaw_user.last_name.casefold() == "aplin"
        ):
            return
        approved = set(Membership.objects.filter(
            group_id=shaw.team.group_id, user_id__in=(38, 41), status="ACTIVE"
        ).values_list("user_id", flat=True))
        if approved != {38, 41}:
            return

        if zack.user_id is None and not Player.objects.filter(
            team_id=1, user_id=38
        ).exists():
            zack.user_id = 38
            zack.save(update_fields=("user", "updated_at"))
            Profile.objects.get_or_create(
                player_id=zack.id, defaults={"email": zack_user.email or ""}
            )

        # Preserve Shaw's original #69 record with its Game Book stats.
        if shaw.user_id == 41 and not duplicate.is_active and duplicate.merged_into_id == shaw.id:
            return  # Already linked and merged.
        if shaw.user_id is not None or duplicate.user_id != 41 or not duplicate.is_active:
            return
        if Player.objects.filter(team_id=1, user_id=41).exclude(pk=16).exists():
            return
        # If the player has gained independent stats or financial history,
        # require the interactive manager merge so nothing is lost.
        if (
            PlateAppearance.objects.filter(player_id=16).exists()
            or StatEntry.objects.filter(player_id=16).exists()
            or Fee.objects.filter(player_id=16).exists()
            or Award.objects.filter(player_id=16).exists()
            or Moment.objects.filter(player_id=16).exists()
            or Substitution.objects.filter(
                Q(outgoing_player_id=16) | Q(incoming_player_id=16)
            ).exists()
        ):
            return
        source_games = set(Lineup.objects.filter(player_id=16).values_list("game_id", flat=True))
        if Lineup.objects.filter(player_id=5, game_id__in=source_games).exists():
            return

        original_profile = Profile.objects.filter(player_id=5).first()
        duplicate_profile = Profile.objects.filter(player_id=16).first()
        if duplicate_profile:
            if original_profile:
                for field in (
                    "email", "phone", "profile_photo", "card_photo_data",
                    "card_photo_mime", "card_nickname", "date_of_birth",
                    "emergency_contact_name", "emergency_contact_phone", "notes",
                ):
                    if not getattr(original_profile, field) and getattr(duplicate_profile, field):
                        setattr(original_profile, field, getattr(duplicate_profile, field))
                original_profile.save()
            else:
                duplicate_profile.player_id = 5
                duplicate_profile.save(update_fields=("player", "updated_at"))
        else:
            Profile.objects.get_or_create(
                player_id=5, defaults={"email": shaw_user.email or ""}
            )

        Lineup.objects.filter(player_id=16).update(player_id=5)
        # Transfer the unique account link without ever changing original PAs.
        duplicate.user_id = None
        duplicate.is_active = False
        duplicate.merged_into_id = 5
        duplicate.save(update_fields=("user", "is_active", "merged_into", "updated_at"))
        shaw.user_id = 41
        shaw.save(update_fields=("user", "updated_at"))


class Migration(migrations.Migration):
    dependencies = [
        ("platform_sports", "0018_team_engagement_profiles_awards"),
    ]

    operations = [
        migrations.RunPython(link_bed_springs_accounts, migrations.RunPython.noop),
    ]
