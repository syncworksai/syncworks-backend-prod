from __future__ import annotations

from django.db import migrations


SQLITE_REBUILD_SQL = r"""
PRAGMA foreign_keys=OFF;

CREATE TABLE IF NOT EXISTS user_accounts_invoice_new (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    ticket_id bigint NULL REFERENCES user_accounts_ticket (id) DEFERRABLE INITIALLY DEFERRED,
    title varchar(255) NOT NULL DEFAULT '',
    notes text NOT NULL DEFAULT '',
    subtotal decimal NOT NULL DEFAULT '0.00',
    tax decimal NOT NULL DEFAULT '0.00',
    total decimal NOT NULL DEFAULT '0.00',
    status varchar(20) NOT NULL DEFAULT 'DRAFT',
    due_date date NULL,
    payment_method varchar(20) NOT NULL DEFAULT 'CARD',
    amount_paid decimal NOT NULL DEFAULT '0.00',
    paid_at datetime NULL,
    platform_fee_rate_bps integer unsigned NOT NULL DEFAULT 100,
    platform_fee_amount decimal NOT NULL DEFAULT '0.00',
    platform_fee_collected bool NOT NULL DEFAULT 0,
    platform_fee_collected_at datetime NULL,
    stripe_checkout_session_id varchar(255) NOT NULL DEFAULT '',
    stripe_payment_intent_id varchar(255) NOT NULL DEFAULT '',
    stripe_charge_id varchar(255) NOT NULL DEFAULT '',
    stripe_transfer_id varchar(255) NOT NULL DEFAULT '',
    created_at datetime NOT NULL,
    updated_at datetime NOT NULL
);

INSERT INTO user_accounts_invoice_new (
    id,
    ticket_id,
    title,
    notes,
    subtotal,
    tax,
    total,
    status,
    due_date,
    payment_method,
    amount_paid,
    paid_at,
    platform_fee_rate_bps,
    platform_fee_amount,
    platform_fee_collected,
    platform_fee_collected_at,
    stripe_checkout_session_id,
    stripe_payment_intent_id,
    stripe_charge_id,
    stripe_transfer_id,
    created_at,
    updated_at
)
SELECT
    id,
    ticket_id,
    '' as title,
    COALESCE(memo, '') as notes,
    ROUND(COALESCE(amount_cents, 0) / 100.0, 2) as subtotal,
    0.00 as tax,
    ROUND(COALESCE(amount_cents, 0) / 100.0, 2) as total,
    COALESCE(status, 'DRAFT') as status,
    due_date,
    'CARD' as payment_method,
    CASE
        WHEN status = 'PAID' THEN ROUND(COALESCE(amount_cents, 0) / 100.0, 2)
        ELSE 0.00
    END as amount_paid,
    paid_at,
    100 as platform_fee_rate_bps,
    0.00 as platform_fee_amount,
    CASE
        WHEN status = 'PAID' THEN 1
        ELSE 0
    END as platform_fee_collected,
    CASE
        WHEN status = 'PAID' THEN paid_at
        ELSE NULL
    END as platform_fee_collected_at,
    '' as stripe_checkout_session_id,
    '' as stripe_payment_intent_id,
    '' as stripe_charge_id,
    '' as stripe_transfer_id,
    COALESCE(created_at, CURRENT_TIMESTAMP) as created_at,
    COALESCE(created_at, CURRENT_TIMESTAMP) as updated_at
FROM user_accounts_invoice;

DROP TABLE user_accounts_invoice;
ALTER TABLE user_accounts_invoice_new RENAME TO user_accounts_invoice;

CREATE INDEX IF NOT EXISTS user_accounts_invoice_ticket_status_idx
ON user_accounts_invoice (ticket_id, status);

CREATE INDEX IF NOT EXISTS user_accounts_invoice_status_created_idx
ON user_accounts_invoice (status, created_at);

CREATE INDEX IF NOT EXISTS user_accounts_invoice_payment_status_idx
ON user_accounts_invoice (payment_method, status);

PRAGMA foreign_keys=ON;
"""

SQLITE_REVERSE_SQL = r"""
SELECT 1;
"""


def rebuild_invoice_table_sqlite_only(apps, schema_editor):
    if schema_editor.connection.vendor != "sqlite":
        return

    statements = [s.strip() for s in SQLITE_REBUILD_SQL.split(";") if s.strip()]
    for statement in statements:
        schema_editor.execute(statement + ";")


def reverse_sqlite_only(apps, schema_editor):
    if schema_editor.connection.vendor != "sqlite":
        return

    statements = [s.strip() for s in SQLITE_REVERSE_SQL.split(";") if s.strip()]
    for statement in statements:
        schema_editor.execute(statement + ";")


class Migration(migrations.Migration):

    dependencies = [
        ("user_accounts", "0073_invoice_line_items"),
    ]

    operations = [
        migrations.RunPython(
            rebuild_invoice_table_sqlite_only,
            reverse_code=reverse_sqlite_only,
        ),
    ]