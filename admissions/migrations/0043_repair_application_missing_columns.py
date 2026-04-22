from django.db import migrations


def _column_exists(connection, table_name, column_name):
    with connection.cursor() as cursor:
        table_description = connection.introspection.get_table_description(cursor, table_name)
    return any(column.name == column_name for column in table_description)


def add_missing_application_columns(apps, schema_editor):
    Application = apps.get_model("admissions", "Application")
    table_name = Application._meta.db_table

    missing_fields = [
        ("school_pay_reference", "school_pay_reference"),
        ("entered_by", "entered_by_id"),
    ]

    for field_name, column_name in missing_fields:
        if not _column_exists(schema_editor.connection, table_name, column_name):
            field = Application._meta.get_field(field_name)
            schema_editor.add_field(Application, field)


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0042_merge_20260420_2145"),
    ]

    operations = [
        migrations.RunPython(add_missing_application_columns, migrations.RunPython.noop),
    ]
