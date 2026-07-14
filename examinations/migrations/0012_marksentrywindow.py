from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("Programs", "0014_timetablesession_session_date"),
        ("examinations", "0011_alter_examcardtoken_id_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="MarksEntryWindow",
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
                ("name", models.CharField(max_length=160)),
                ("opens_at", models.DateTimeField(blank=True, null=True)),
                ("closes_at", models.DateTimeField(blank=True, null=True)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("notes", models.TextField(blank=True, default="")),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "closed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="closed_marks_entry_windows",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "course_unit",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="marks_entry_windows",
                        to="Programs.courseunit",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_marks_entry_windows",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "program_batch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="marks_entry_windows",
                        to="Programs.programbatch",
                    ),
                ),
                (
                    "semester",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="marks_entry_windows",
                        to="Programs.semester",
                    ),
                ),
            ],
            options={
                "ordering": [
                    "-is_active",
                    "program_batch__name",
                    "semester__order",
                    "course_unit__code",
                ],
                "permissions": [
                    (
                        "manage_marks_windows",
                        "Can open and close examination marks entry windows",
                    )
                ],
                "indexes": [
                    models.Index(
                        fields=[
                            "program_batch",
                            "semester",
                            "course_unit",
                            "is_active",
                        ],
                        name="examination_program_2bba3c_idx",
                    ),
                    models.Index(
                        fields=["opens_at", "closes_at"],
                        name="examination_opens_a_363d37_idx",
                    ),
                ],
            },
        ),
    ]
