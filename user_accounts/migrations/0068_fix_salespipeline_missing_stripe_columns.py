from django.db import migrations


def _sqlite_columns(schema_editor, table_name: str) -> set[str]:
    cur = schema_editor.connection.cursor()
    cur.execute(f"PRAGMA table_info({table_name});")
    return {str(row[1]) for row in cur.fetchall()}


def add_missing_stripe_columns(apps, schema_editor):
    table = "user_accounts_salespipeline"
    conn = schema_editor.connection

    if conn.vendor == "sqlite":
        existing = _sqlite_columns(schema_editor, table)
        for col in ("stripe_customer_id", "stripe_subscription_id", "stripe_subscription_item_id"):
            if col not in existing:
                schema_editor.execute(
                    f"ALTER TABLE {table} ADD COLUMN {col} varchar(128) NOT NULL DEFAULT '';"
                )
        return

    # PostgreSQL (and other engines that support IF NOT EXISTS)
    schema_editor.execute(
        f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS stripe_customer_id varchar(128) NOT NULL DEFAULT '';"
    )
    schema_editor.execute(
        f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS stripe_subscription_id varchar(128) NOT NULL DEFAULT '';"
    )
    schema_editor.execute(
        f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS stripe_subscription_item_id varchar(128) NOT NULL DEFAULT '';"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("user_accounts", "0067_alter_userbillingprofile_options"),
    ]

    operations = [
        migrations.RunPython(add_missing_stripe_columns, reverse_code=migrations.RunPython.noop),
    ]
