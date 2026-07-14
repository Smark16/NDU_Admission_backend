from django.db import migrations, models
import django.db.models.deletion


def _column_names(schema_editor, table: str) -> set[str]:
    with schema_editor.connection.cursor() as cursor:
        description = schema_editor.connection.introspection.get_table_description(
            cursor, table
        )
    return {col.name for col in description}


def add_campus_fields_if_missing(apps, schema_editor):
    cols = _column_names(schema_editor, "accounts_user")
    if schema_editor.connection.vendor == "sqlite":
        if "allow_multi_campus_per_day" not in cols:
            schema_editor.execute(
                "ALTER TABLE accounts_user "
                "ADD COLUMN allow_multi_campus_per_day bool NOT NULL DEFAULT 0"
            )
        if "primary_campus_id" not in cols:
            schema_editor.execute(
                "ALTER TABLE accounts_user "
                "ADD COLUMN primary_campus_id integer NULL "
                "REFERENCES accounts_campus (id) DEFERRABLE INITIALLY DEFERRED"
            )
        return

    User = apps.get_model("accounts", "User")
    Campus = apps.get_model("accounts", "Campus")
    if "allow_multi_campus_per_day" not in cols:
        field = models.BooleanField(default=False)
        field.set_attributes_from_name("allow_multi_campus_per_day")
        schema_editor.add_field(User, field)
    if "primary_campus_id" not in cols:
        field = models.ForeignKey(
            Campus,
            on_delete=django.db.models.deletion.SET_NULL,
            null=True,
            blank=True,
            related_name="primary_campus_users",
        )
        field.set_attributes_from_name("primary_campus")
        schema_editor.add_field(User, field)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0027_alter_systemsettings_id_card_templates"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="user",
                    name="allow_multi_campus_per_day",
                    field=models.BooleanField(
                        default=False,
                        help_text="Allow the user to operate across multiple campuses on the same day.",
                    ),
                ),
                migrations.AddField(
                    model_name="user",
                    name="primary_campus",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="primary_campus_users",
                        to="accounts.campus",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunPython(
                    add_campus_fields_if_missing,
                    migrations.RunPython.noop,
                ),
            ],
        ),
    ]
