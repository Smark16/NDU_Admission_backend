# CourseUnitSectionLecturer for per-section staff assignment

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("Programs", "0024_timetablesession_teaching_section"),
    ]

    operations = [
        migrations.CreateModel(
            name="CourseUnitSectionLecturer",
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
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "course_unit",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="section_lecturers",
                        to="Programs.courseunit",
                    ),
                ),
                (
                    "lecturer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="section_course_assignments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "teaching_section",
                    models.ForeignKey(
                        blank=True,
                        help_text="Null = assigned to all sections (whole cohort) on this unit.",
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="course_unit_lecturers",
                        to="Programs.teachingsection",
                    ),
                ),
            ],
            options={
                "verbose_name": "Course unit section lecturer",
                "verbose_name_plural": "Course unit section lecturers",
            },
        ),
        migrations.AddConstraint(
            model_name="courseunitsectionlecturer",
            constraint=models.UniqueConstraint(
                condition=models.Q(teaching_section__isnull=True),
                fields=("course_unit", "lecturer"),
                name="programs_cu_section_lecturer_all_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="courseunitsectionlecturer",
            constraint=models.UniqueConstraint(
                condition=models.Q(teaching_section__isnull=False),
                fields=("course_unit", "teaching_section", "lecturer"),
                name="programs_cu_section_lecturer_section_unique",
            ),
        ),
    ]
