from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0009_feehead_feeplan_feeplanrule_registrationsettings_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="feeplanrule",
            name="payable_term_number",
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text="Optional: term number when this fee becomes due (used with payable_year_of_study).",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="feeplanrule",
            name="payable_year_of_study",
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text="Optional: year-of-study when this fee becomes due (for scheduled other fees).",
                null=True,
            ),
        ),
    ]

