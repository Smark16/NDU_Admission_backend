from django.db import migrations, models


def _column_names(schema_editor, table):
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(cursor, table)
    return {getattr(col, "name", None) or col[0] for col in description}


def add_sponsor_type_if_missing(apps, schema_editor):
    table = "payments_scholarshipprogramme"
    if "sponsor_type" in _column_names(schema_editor, table):
        return
    ScholarshipProgramme = apps.get_model("payments", "ScholarshipProgramme")
    field = models.CharField(
        max_length=32,
        choices=[
            ("state_house", "State House"),
            ("hesfb", "HESFB"),
            ("fawe", "FAWE"),
            ("church", "Church sponsored"),
            ("other", "Other / custom"),
        ],
        default="other",
        db_index=True,
        help_text="Taxonomy for State House, HESFB, FAWE, church, etc.",
    )
    field.set_attributes_from_name("sponsor_type")
    schema_editor.add_field(ScholarshipProgramme, field)


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0016_merge_20260805_2139"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="scholarshipprogramme",
                    name="sponsor_type",
                    field=models.CharField(
                        choices=[
                            ("state_house", "State House"),
                            ("hesfb", "HESFB"),
                            ("fawe", "FAWE"),
                            ("church", "Church sponsored"),
                            ("other", "Other / custom"),
                        ],
                        db_index=True,
                        default="other",
                        help_text="Taxonomy for State House, HESFB, FAWE, church, etc.",
                        max_length=32,
                    ),
                ),
            ],
            database_operations=[
                migrations.RunPython(add_sponsor_type_if_missing, migrations.RunPython.noop),
            ],
        ),
    ]
