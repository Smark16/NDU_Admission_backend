# Generated manually for TeachingSection Phase 1

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("Programs", "0022_clear_programbatch_offer_dates"),
    ]

    operations = [
        migrations.CreateModel(
            name="TeachingSection",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "code",
                    models.CharField(
                        help_text="Short code unique within the cohort (e.g. MAIN, A, B).",
                        max_length=20,
                    ),
                ),
                (
                    "name",
                    models.CharField(
                        help_text="Display name (e.g. Main, Section A).",
                        max_length=100,
                    ),
                ),
                (
                    "is_default",
                    models.BooleanField(
                        default=False,
                        help_text=(
                            "Catch-all section for new enrollments. Exactly one per cohort."
                        ),
                    ),
                ),
                (
                    "max_capacity",
                    models.PositiveIntegerField(
                        default=120,
                        help_text=(
                            "Teaching capacity warning/limit when moving students "
                            "(0 = unlimited)."
                        ),
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "program_batch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="teaching_sections",
                        to="Programs.programbatch",
                    ),
                ),
            ],
            options={
                "verbose_name": "Teaching Section",
                "verbose_name_plural": "Teaching Sections",
                "ordering": ["-is_default", "code", "name"],
                "unique_together": {("program_batch", "code")},
            },
        ),
        migrations.AddConstraint(
            model_name="teachingsection",
            constraint=models.UniqueConstraint(
                condition=models.Q(is_default=True),
                fields=("program_batch",),
                name="programs_teachingsection_one_default_per_batch",
            ),
        ),
        migrations.AddField(
            model_name="studentprogrammeenrollment",
            name="teaching_section",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Teaching section within the academic cohort. New enrollments land "
                    "on the cohort default section; staff may move students later."
                ),
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="student_enrollments",
                to="Programs.teachingsection",
            ),
        ),
    ]
