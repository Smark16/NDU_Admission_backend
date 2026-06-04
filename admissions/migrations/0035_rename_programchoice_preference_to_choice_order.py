"""Align ApplicationProgramChoice column name with the model (choice_order)."""

from django.db import migrations


def _column_names(schema_editor, table: str) -> set[str]:
    with schema_editor.connection.cursor() as cursor:
        description = schema_editor.connection.introspection.get_table_description(
            cursor, table
        )
    return {col.name for col in description}


def rename_preference_to_choice_order(apps, schema_editor):
    table = "admissions_applicationprogramchoice"
    cols = _column_names(schema_editor, table)
    if "choice_order" in cols or "preference" not in cols:
        return

    vendor = schema_editor.connection.vendor
    if vendor == "sqlite":
        schema_editor.execute(
            f"ALTER TABLE {table} RENAME COLUMN preference TO choice_order"
        )
    elif vendor == "postgresql":
        schema_editor.execute(
            f'ALTER TABLE {table} RENAME COLUMN preference TO choice_order'
        )
    else:
        schema_editor.execute(
            f"ALTER TABLE {table} CHANGE preference choice_order INTEGER UNSIGNED NOT NULL"
        )


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0034_alter_additionalqualifications_additional_qualification_year"),
    ]

    operations = [
        migrations.RunPython(
            rename_preference_to_choice_order,
            migrations.RunPython.noop,
        ),
    ]
