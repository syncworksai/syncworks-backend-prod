from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
from django.db.migrations.state import ProjectState


def rebuild_empty_legacy_invoice_table_for_postgres(apps, schema_editor):
    """Only a new, empty PostgreSQL install may replace the legacy invoice table.

    Before 0055, historical migrations leave the old ticket-invoice schema in
    the database. The state-only CreateModel below describes a different table;
    without a physical transition, 0057 cannot build an index on business_id.
    Existing nonempty invoice tables are NEVER replaced automatically.
    """
    if schema_editor.connection.vendor != "postgresql":
        return

    LegacyInvoice = apps.get_model("user_accounts", "Invoice")
    table = LegacyInvoice._meta.db_table
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f'SELECT EXISTS(SELECT 1 FROM "{table}" LIMIT 1)')
        if cursor.fetchone()[0]:
            raise RuntimeError(
                "Invoice migration 0055 refuses to replace a nonempty legacy "
                "invoice table. Preserve and reconcile existing invoices first."
            )

    # Derive the new table from precisely the same CreateModel operation that
    # advances Django migration state, instead of maintaining separate SQL.
    new_state = ProjectState.from_apps(apps)
    new_state.remove_model("user_accounts", "invoice")
    INVOICE_CREATE_OPERATION.state_forwards("user_accounts", new_state)
    NewInvoice = new_state.apps.get_model("user_accounts", "Invoice")
    schema_editor.delete_model(LegacyInvoice)
    schema_editor.create_model(NewInvoice)




INVOICE_CREATE_OPERATION = migrations.CreateModel(
    name="Invoice",
    fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("kind", models.CharField(choices=[("JOB", "Job Invoice"), ("CASH_FEE", "Cash Fee Invoice")], default="JOB", max_length=20)),
        ("status", models.CharField(choices=[("OPEN", "Open"), ("PAID", "Paid"), ("OVERDUE", "Overdue"), ("VOID", "Void")], default="OPEN", max_length=20)),
        ("currency", models.CharField(default="usd", max_length=10)),
        ("amount_cents", models.PositiveIntegerField(default=0)),
        ("period_start", models.DateField(blank=True, null=True)),
        ("period_end", models.DateField(blank=True, null=True)),
        ("due_date", models.DateField(blank=True, null=True)),
        ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
        ("paid_at", models.DateTimeField(blank=True, null=True)),
        ("memo", models.CharField(blank=True, default="", max_length=255)),
        ("business", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="invoices", to="user_accounts.business")),
        ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_invoices", to=settings.AUTH_USER_MODEL)),
    ],
    options={"ordering": ["-created_at"]},
)


class Migration(migrations.Migration):

    dependencies = [
        ("user_accounts", "0053_salespipeline_is_locked_salesevent"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    # Fail closed on existing invoice data; rebuild only an empty legacy
    # invoice table on a fresh PostgreSQL installation.
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(
                rebuild_empty_legacy_invoice_table_for_postgres,
                reverse_code=migrations.RunPython.noop,
            )],
            state_operations=[INVOICE_CREATE_OPERATION],
        ),
    ]
