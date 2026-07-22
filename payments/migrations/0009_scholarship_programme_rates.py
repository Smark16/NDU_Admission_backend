# Generated manually — programme rates + awarding_mode

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("Programs", "0019_course_material"),
        ("payments", "0008_scholarships"),
    ]

    operations = [
        migrations.AddField(
            model_name="scholarshipprogramme",
            name="awarding_mode",
            field=models.CharField(
                choices=[
                    ("by_programme", "By academic programme (rate table)"),
                    ("per_student", "Per student (manual amount)"),
                ],
                default="per_student",
                help_text="HESFB-style rates vs Sports-style per-student amounts.",
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name="ScholarshipProgrammeRate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "amount",
                    models.DecimalField(
                        decimal_places=2,
                        help_text="Award amount for students on this academic programme.",
                        max_digits=14,
                    ),
                ),
                ("notes", models.CharField(blank=True, default="", max_length=255)),
                (
                    "academic_program",
                    models.ForeignKey(
                        help_text="Student's admitted academic programme (e.g. BSc Computer Science).",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="scholarship_rates",
                        to="Programs.program",
                    ),
                ),
                (
                    "scholarship",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="programme_rates",
                        to="payments.scholarshipprogramme",
                    ),
                ),
            ],
            options={
                "verbose_name": "Scholarship programme rate",
                "verbose_name_plural": "Scholarship programme rates",
                "ordering": ["academic_program__name"],
                "unique_together": {("scholarship", "academic_program")},
            },
        ),
    ]
