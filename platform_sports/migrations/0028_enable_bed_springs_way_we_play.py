from django.db import migrations


def enable_way_we_play(apps, schema_editor):
    SportsTeam = apps.get_model("platform_sports", "SportsTeam")
    teams = SportsTeam.objects.select_related("group").filter(group__name__icontains="bed springs baptist")
    for team in teams:
        rules = dict(team.badge_rules or {})
        rules["way_we_play_enabled"] = True
        rules.setdefault("way_score_formula", "WAY-1.0")
        team.badge_rules = rules
        team.save(update_fields=("badge_rules", "updated_at"))


def disable_way_we_play(apps, schema_editor):
    SportsTeam = apps.get_model("platform_sports", "SportsTeam")
    for team in SportsTeam.objects.all():
        rules = dict(team.badge_rules or {})
        if "way_we_play_enabled" not in rules and "way_score_formula" not in rules:
            continue
        rules.pop("way_we_play_enabled", None)
        rules.pop("way_score_formula", None)
        team.badge_rules = rules
        team.save(update_fields=("badge_rules", "updated_at"))


class Migration(migrations.Migration):
    dependencies = [
        ("platform_sports", "0027_bed_springs_combined_batting_totals"),
    ]

    operations = [
        migrations.RunPython(enable_way_we_play, disable_way_we_play),
    ]
