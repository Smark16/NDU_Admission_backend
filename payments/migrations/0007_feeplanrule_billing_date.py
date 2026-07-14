from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0006_regsettings_auto_assign_course_units_after_commitment"),
    ]

    operations = [
        migrations.AddField(
            model_name="feeplanrule",
            name="billing_date",
            field=models.DateField(
                blank=True,
                help_text="Date this fee becomes visible and billable on the student portal.",
                null=True,
            ),
        ),
    ]
