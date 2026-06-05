from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0005_restore_other_fee_schedule_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="registrationsettings",
            name="auto_assign_course_units_after_commitment",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "When enabled, commitment-based enrollment activation also auto-assigns "
                    "active course units for the student's current batch semester."
                ),
            ),
        ),
    ]

