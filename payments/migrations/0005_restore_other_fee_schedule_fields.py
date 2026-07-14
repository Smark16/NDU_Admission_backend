# Restores fields for other_fee_schedule when 0003 was not applied (columns may already exist).

from django.db import migrations, models


def _payable_columns_present(schema_editor) -> bool:
    table = "payments_feeplanrule"
    with schema_editor.connection.cursor() as cursor:
        if schema_editor.connection.vendor == "postgresql":
            cursor.execute(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = %s
                  AND column_name = 'payable_term_number'
                LIMIT 1
                """,
                [table],
            )
            return cursor.fetchone() is not None
        description = schema_editor.connection.introspection.get_table_description(
            cursor, table
        )
    return any(col.name == "payable_term_number" for col in description)


def ensure_payable_columns(apps, schema_editor):
    if _payable_columns_present(schema_editor):
        return
    FeePlanRule = apps.get_model("payments", "FeePlanRule")
    field_y = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="When set with payable_term_number, fee is due at this curriculum year/term.",
    )
    field_t = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Term within payable_year_of_study (1-based).",
    )
    field_y.set_attributes_from_name("payable_year_of_study")
    field_t.set_attributes_from_name("payable_term_number")
    schema_editor.add_field(FeePlanRule, field_y)
    schema_editor.add_field(FeePlanRule, field_t)


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0004_alter_tuitionledger_settlement_bank_code"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(ensure_payable_columns, migrations.RunPython.noop),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="feeplanrule",
                    name="payable_term_number",
                    field=models.PositiveSmallIntegerField(
                        blank=True,
                        help_text="Term within payable_year_of_study (1-based).",
                        null=True,
                    ),
                ),
                migrations.AddField(
                    model_name="feeplanrule",
                    name="payable_year_of_study",
                    field=models.PositiveSmallIntegerField(
                        blank=True,
                        help_text="When set with payable_term_number, fee is due at this curriculum year/term.",
                        null=True,
                    ),
                ),
                migrations.AlterField(
                    model_name="feeplan",
                    name="plan_type",
                    field=models.CharField(
                        choices=[
                            ("application", "Application fees"),
                            ("tuition", "Tuition"),
                            ("general", "General / service fees"),
                            (
                                "other_schedule",
                                "Scheduled other fees (year/term milestones)",
                            ),
                        ],
                        max_length=20,
                    ),
                ),
            ],
        ),
    ]
