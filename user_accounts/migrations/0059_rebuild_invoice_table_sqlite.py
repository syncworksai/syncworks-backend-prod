from __future__ import annotations

from django.db import migrations


def _table_exists(schema_editor, table_name: str) -> bool:
    if schema_editor.connection.vendor != "sqlite":
        return False
    cur = schema_editor.connection.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=%s;", [table_name])
    return cur.fetchone() is not None


def _table_cols(schema_editor, table_name: str) -> set[str]:
    if schema_editor.connection.vendor != "sqlite":
        return set()
    cur = schema_editor.connection.cursor()
    cur.execute(f"PRAGMA table_info({table_name});")
    return {str(r[1]) for r in cur.fetchall()}


def rebuild_invoice_table(apps, schema_editor):
    if schema_editor.connection.vendor != "sqlite":
        return

    new_table = "user_accounts_invoice"
    old_table = "user_accounts_invoice_old"

    has_new = _table_exists(schema_editor, new_table)
    has_old = _table_exists(schema_editor, old_table)

    schema_editor.execute("PRAGMA foreign_keys=OFF;")

    try:
        # If we have invoice but not invoice_old, rename invoice -> invoice_old so we can rebuild cleanly
        if has_new and not has_old:
            schema_editor.execute(f"ALTER TABLE {new_table} RENAME TO {old_table};")
            has_old = True
            has_new = False

        # Create the NEW (business-based) invoice table that matches your current Invoice model
        schema_editor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_accounts_invoice (
                id integer NOT NULL PRIMARY KEY AUTOINCREMENT,
                business_id bigint NOT NULL REFERENCES user_accounts_business (id) DEFERRABLE INITIALLY DEFERRED,
                kind varchar(20) NOT NULL,
                status varchar(20) NOT NULL,
                currency varchar(10) NOT NULL,
                amount_cents integer NOT NULL,
                period_start date NULL,
                period_end date NULL,
                due_date date NULL,
                created_by_id bigint NULL REFERENCES user_accounts_user (id) DEFERRABLE INITIALLY DEFERRED,
                created_at datetime NOT NULL,
                paid_at datetime NULL,
                memo varchar(255) NOT NULL
            );
            """
        )

        # Copy data best-effort from invoice_old -> new invoice
        if has_old:
            cols = _table_cols(schema_editor, old_table)

            # CASE A: old already had business_id
            if "business_id" in cols:
                has_kind = "kind" in cols
                has_status = "status" in cols
                has_currency = "currency" in cols
                has_amount_cents = "amount_cents" in cols
                has_period_start = "period_start" in cols
                has_period_end = "period_end" in cols
                has_due_date = "due_date" in cols
                has_created_by_id = "created_by_id" in cols
                has_created_at = "created_at" in cols
                has_paid_at = "paid_at" in cols
                has_memo = "memo" in cols
                has_title = "title" in cols

                schema_editor.execute(
                    f"""
                    INSERT INTO user_accounts_invoice (
                        id, business_id, kind, status, currency, amount_cents,
                        period_start, period_end, due_date, created_by_id,
                        created_at, paid_at, memo
                    )
                    SELECT
                        id,
                        business_id,
                        {("COALESCE(kind,'JOB')" if has_kind else "'JOB'")},
                        {("COALESCE(status,'OPEN')" if has_status else "'OPEN'")},
                        {("COALESCE(currency,'usd')" if has_currency else "'usd'")},
                        {("COALESCE(amount_cents,0)" if has_amount_cents else "0")},
                        {("period_start" if has_period_start else "NULL")},
                        {("period_end" if has_period_end else "NULL")},
                        {("due_date" if has_due_date else "NULL")},
                        {("created_by_id" if has_created_by_id else "NULL")},
                        {("COALESCE(created_at, CURRENT_TIMESTAMP)" if has_created_at else "CURRENT_TIMESTAMP")},
                        {("paid_at" if has_paid_at else "NULL")},
                        {("COALESCE(memo,'')" if has_memo else ("COALESCE(title,'')" if has_title else "''"))}
                    FROM {old_table};
                    """
                )

            # CASE B: old is Ticket-based invoice schema (has ticket_id, total/status/title/notes)
            elif "ticket_id" in cols:
                has_total = "total" in cols
                has_amount_cents = "amount_cents" in cols
                has_paid_at = "paid_at" in cols
                has_due_date = "due_date" in cols
                has_created_at = "created_at" in cols
                has_title = "title" in cols
                has_notes = "notes" in cols
                has_memo = "memo" in cols
                has_status = "status" in cols

                amount_expr = "0"
                if has_amount_cents:
                    amount_expr = "COALESCE(i.amount_cents,0)"
                elif has_total:
                    amount_expr = "CAST(ROUND(COALESCE(i.total,0) * 100) AS INTEGER)"

                memo_expr = "''"
                if has_title and has_notes:
                    memo_expr = "TRIM(COALESCE(i.title,'') || CASE WHEN i.notes IS NOT NULL AND i.notes!='' THEN ' — ' || i.notes ELSE '' END)"
                elif has_title:
                    memo_expr = "COALESCE(i.title,'')"
                elif has_memo:
                    memo_expr = "COALESCE(i.memo,'')"

                status_expr = "'OPEN'"
                if has_status:
                    status_expr = """
                    CASE
                        WHEN UPPER(i.status)='PAID' THEN 'PAID'
                        WHEN UPPER(i.status)='VOID' THEN 'VOID'
                        ELSE 'OPEN'
                    END
                    """

                schema_editor.execute(
                    f"""
                    INSERT INTO user_accounts_invoice (
                        business_id, kind, status, currency, amount_cents,
                        period_start, period_end, due_date, created_by_id,
                        created_at, paid_at, memo
                    )
                    SELECT
                        COALESCE(t.payer_business_id, t.assigned_business_id, 1) as business_id,
                        'JOB' as kind,
                        {status_expr} as status,
                        'usd' as currency,
                        {amount_expr} as amount_cents,
                        NULL as period_start,
                        NULL as period_end,
                        {("i.due_date" if has_due_date else "NULL")} as due_date,
                        NULL as created_by_id,
                        {("COALESCE(i.created_at, CURRENT_TIMESTAMP)" if has_created_at else "CURRENT_TIMESTAMP")} as created_at,
                        {("i.paid_at" if has_paid_at else "NULL")} as paid_at,
                        {memo_expr} as memo
                    FROM {old_table} i
                    LEFT JOIN user_accounts_ticket t ON t.id = i.ticket_id;
                    """
                )

            # Drop old table after copy attempt
            schema_editor.execute(f"DROP TABLE {old_table};")

        # Indexes expected by Invoice.Meta
        schema_editor.execute(
            "CREATE INDEX IF NOT EXISTS user_accoun_busines_f53f7b_idx ON user_accounts_invoice (business_id, kind, status);"
        )
        schema_editor.execute(
            "CREATE INDEX IF NOT EXISTS user_accoun_kind_e004ab_idx ON user_accounts_invoice (kind, period_start, period_end);"
        )
        schema_editor.execute(
            "CREATE INDEX IF NOT EXISTS user_accoun_due_dat_385a3c_idx ON user_accounts_invoice (due_date, status);"
        )
    finally:
        schema_editor.execute("PRAGMA foreign_keys=ON;")


class Migration(migrations.Migration):

    dependencies = [
        ("user_accounts", "0058_ticket_cash_confirmed_at_and_more"),
    ]

    operations = [
        migrations.RunPython(rebuild_invoice_table, reverse_code=migrations.RunPython.noop),
    ]