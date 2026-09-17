from django.db import migrations


def correct_bed_springs_dues(apps, schema_editor):
    SportsTeam = apps.get_model("platform_sports", "SportsTeam")
    TeamFee = apps.get_model("platform_sports", "TeamFee")
    TeamFeeAssignment = apps.get_model("platform_sports", "TeamFeeAssignment")

    team = SportsTeam.objects.filter(
        group__name="Bed Springs Baptist",
        sport="SOFTBALL",
    ).first()
    if not team:
        return

    corrections = {
        "league fee": 5000,
        "jerseys": 2500,
    }
    for fee in TeamFee.objects.filter(team=team, is_active=True):
        target = corrections.get((fee.title or "").strip().lower())
        if target is None:
            continue
        fee.amount_cents = target
        fee.save(update_fields=("amount_cents", "updated_at"))
        TeamFeeAssignment.objects.filter(
            fee=fee,
            status__in=("DUE", "PARTIAL"),
            amount_paid_cents=0,
        ).update(amount_cents=target)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("platform_sports", "0004_seed_bed_springs_fall_2026"),
    ]

    operations = [
        migrations.RunPython(correct_bed_springs_dues, noop_reverse),
    ]
