# backend/user_accounts/migrations/0064_backfill_business_card_codes.py
import secrets

from django.db import migrations


def _gen_code() -> str:
    return "SW-" + secrets.token_urlsafe(12)


def backfill_codes(apps, schema_editor):
    Business = apps.get_model("user_accounts", "Business")

    qs = Business.objects.filter(business_card_code__isnull=True) | Business.objects.filter(
        business_card_code=""
    )

    # IMPORTANT: Using apps.get_model, not importing Business directly
    for b in qs.iterator():
        # Try a few times for uniqueness
        for _ in range(10):
            code = _gen_code()
            if not Business.objects.filter(business_card_code=code).exists():
                b.business_card_code = code
                b.save(update_fields=["business_card_code"])
                break
        else:
            # ultra-rare fallback
            b.business_card_code = "SW-" + secrets.token_urlsafe(24)
            b.save(update_fields=["business_card_code"])


class Migration(migrations.Migration):

    dependencies = [
        ("user_accounts", "0063_business_card_fields"),
    ]

    operations = [
        migrations.RunPython(backfill_codes, migrations.RunPython.noop),
    ]