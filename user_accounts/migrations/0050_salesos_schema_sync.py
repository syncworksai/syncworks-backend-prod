# backend/user_accounts/migrations/0050_salesos_schema_sync.py
from __future__ import annotations

from django.db import migrations, models


def _column_exists(schema_editor, table_name: str, column_name: str) -> bool:
    """
    Cross-DB check for whether a column exists.
    Works for Postgres / SQLite / MySQL via Django introspection.
    """
    with schema_editor.connection.cursor() as cursor:
        description = schema_editor.connection.introspection.get_table_description(cursor, table_name)
    return any(col.name == column_name for col in description)


def _add_column_if_missing(schema_editor, model, field: models.Field) -> None:
    """
    Adds a DB column even if the field is not declared on the historical model state.
    We attach the field to the model enough for schema_editor.add_field() to work.
    """
    table = model._meta.db_table
    if _column_exists(schema_editor, table, field.name):
        return

    field.set_attributes_from_name(field.name)
    field.model = model
    schema_editor.add_field(model, field)


def forwards(apps, schema_editor):
    """
    Sales OS schema sync.

    IMPORTANT:
    - Do NOT call Model._meta.get_field("updated_at") in a migration unless that field
      exists in the historical migration state.
    - Instead, add columns directly if missing (idempotent).
    """
    SalesPipeline = apps.get_model("user_accounts", "SalesPipeline")

    # Add timestamps to SalesPipeline if missing
    _add_column_if_missing(
        schema_editor,
        SalesPipeline,
        models.DateTimeField(null=True, blank=True, name="created_at"),
    )
    _add_column_if_missing(
        schema_editor,
        SalesPipeline,
        models.DateTimeField(null=True, blank=True, name="updated_at"),
    )

    # If you have other Sales OS models and want timestamps there too,
    # uncomment and ensure the model names exist in user_accounts.
    #
    # SalesStage = apps.get_model("user_accounts", "SalesStage")
    # Prospect = apps.get_model("user_accounts", "Prospect")
    # ProspectActivity = apps.get_model("user_accounts", "ProspectActivity")
    #
    # for M in (SalesStage, Prospect, ProspectActivity):
    #     _add_column_if_missing(schema_editor, M, models.DateTimeField(null=True, blank=True, name="created_at"))
    #     _add_column_if_missing(schema_editor, M, models.DateTimeField(null=True, blank=True, name="updated_at"))


def backwards(apps, schema_editor):
    # No-op on reverse (safety sync migration; we don't drop columns)
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("user_accounts", "0049_salespipeline_add_business"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]