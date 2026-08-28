from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("Programs", "0039_course_unit_class_coordinator"),
    ]

    operations = [
        migrations.AddField(
            model_name="program",
            name="modular_max_credits_per_session",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Modular programmes only: maximum credit units per session (optional).",
                max_digits=5,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="program",
            name="modular_min_credits_per_session",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Modular programmes only: minimum credit units per session (optional).",
                max_digits=5,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="program",
            name="calendar_type",
            field=models.CharField(
                choices=[
                    ("semester", "Semester"),
                    ("trimester", "Trimester"),
                    ("modular", "Modular"),
                ],
                default="semester",
                help_text=(
                    "Academic calendar structure: semester (2 terms/year), "
                    "trimester (3 terms/year), or modular (session / credit-based "
                    "module registration)."
                ),
                max_length=20,
            ),
        ),
    ]
