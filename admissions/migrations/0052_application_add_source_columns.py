"""
Repair DB columns omitted by 0050: that migration used get_field() on the
historical Application model, which did not include `source` or
`legacy_application_number`, so add_field was skipped and the ORM 500s.
"""
from django.db import migrations


def _column_names(connection, table_name):
    with connection.cursor() as cursor:
        desc = connection.introspection.get_table_description(cursor, table_name)
    return {col.name for col in desc}


def add_application_columns(apps, schema_editor):
    Application = apps.get_model("admissions", "Application")
    table = Application._meta.db_table
    conn = schema_editor.connection
    existing = _column_names(conn, table)
    qn = conn.ops.quote_name

    with conn.cursor() as cursor:
        if "source" not in existing:
            cursor.execute(
                f"ALTER TABLE {qn(table)} ADD COLUMN {qn('source')} VARCHAR(30) NOT NULL DEFAULT 'portal'"
            )
        if "legacy_application_number" not in existing:
            cursor.execute(
                f"ALTER TABLE {qn(table)} ADD COLUMN {qn('legacy_application_number')} VARCHAR(100) NULL"
            )


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0051_remove_admittedstudent_approved_at_and_more"),
    ]

    operations = [
        migrations.RunPython(add_application_columns, migrations.RunPython.noop),
    ]
