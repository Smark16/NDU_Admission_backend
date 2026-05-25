# Align DB created on main (choice_order) with development model (preference).

from django.db import migrations


def _table_columns(schema_editor, table):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"PRAGMA table_info({table})")
        return {row[1] for row in cursor.fetchall()}


def forwards(apps, schema_editor):
    table = "admissions_applicationprogramchoice"
    cols = _table_columns(schema_editor, table)
    if "preference" in cols:
        return
    if "choice_order" not in cols:
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f'ALTER TABLE "{table}" RENAME COLUMN "choice_order" TO "preference"'
        )


def backwards(apps, schema_editor):
    table = "admissions_applicationprogramchoice"
    cols = _table_columns(schema_editor, table)
    if "choice_order" in cols:
        return
    if "preference" not in cols:
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f'ALTER TABLE "{table}" RENAME COLUMN "preference" TO "choice_order"'
        )


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0025_application_program_choice"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
