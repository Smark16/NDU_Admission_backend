from django.core.exceptions import FieldDoesNotExist
from django.db import migrations, models


def _column_exists(connection, table_name, column_name):
    with connection.cursor() as cursor:
        table_description = connection.introspection.get_table_description(cursor, table_name)
    return any(column.name == column_name for column in table_description)


def add_missing_application_columns(apps, schema_editor):
    Application = apps.get_model("admissions", "Application")
    table_name = Application._meta.db_table
    conn = schema_editor.connection

    for field_name, column_name in [
        ("legacy_application_number", "legacy_application_number"),
        ("source", "source"),
    ]:
        if _column_exists(conn, table_name, column_name):
            continue

        # Skip columns that are not present on this historical migration state.
        # This keeps the migration idempotent across divergent branch histories.
        try:
            field = Application._meta.get_field(field_name)
        except FieldDoesNotExist:
            continue

        schema_editor.add_field(Application, field)


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0049_repair_application_admitted_by"),
    ]

    operations = [
        migrations.RunPython(add_missing_application_columns, migrations.RunPython.noop),
    ]
