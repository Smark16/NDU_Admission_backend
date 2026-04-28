from django.db import migrations


def _column_exists(connection, table_name, column_name):
    with connection.cursor() as cursor:
        table_description = connection.introspection.get_table_description(cursor, table_name)
    return any(column.name == column_name for column in table_description)


def add_missing_columns(apps, schema_editor):
    conn = schema_editor.connection

    # ── Application table ─────────────────────────────────────────
    Application = apps.get_model("admissions", "Application")
    app_table = Application._meta.db_table

    if not _column_exists(conn, app_table, "admitted_by_id"):
        schema_editor.add_field(Application, Application._meta.get_field("admitted_by"))

    # ── AdmittedStudent table ──────────────────────────────────────
    AdmittedStudent = apps.get_model("admissions", "AdmittedStudent")
    ads_table = AdmittedStudent._meta.db_table

    for field_name, column_name in [
        ("is_approved",  "is_approved"),
        ("approved_by",  "approved_by_id"),
        ("approved_at",  "approved_at"),
    ]:
        if not _column_exists(conn, ads_table, column_name):
            schema_editor.add_field(AdmittedStudent, AdmittedStudent._meta.get_field(field_name))


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0048_admittedstudent_approval_fields"),
    ]

    operations = [
        migrations.RunPython(add_missing_columns, migrations.RunPython.noop),
    ]
