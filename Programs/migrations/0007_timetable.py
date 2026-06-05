from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
        ("Programs", "0006_programbatch_offer_dates"),
    ]

    operations = [
        migrations.CreateModel(
            name="Venue",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(help_text="e.g. LT1, Computer Lab A", max_length=120)),
                ("capacity", models.PositiveIntegerField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "campus",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="venues",
                        to="accounts.campus",
                    ),
                ),
            ],
            options={
                "verbose_name": "Venue",
                "verbose_name_plural": "Venues",
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="TimetableSession",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "day_of_week",
                    models.PositiveSmallIntegerField(
                        choices=[
                            (1, "Monday"),
                            (2, "Tuesday"),
                            (3, "Wednesday"),
                            (4, "Thursday"),
                            (5, "Friday"),
                            (6, "Saturday"),
                            (7, "Sunday"),
                        ]
                    ),
                ),
                ("start_time", models.TimeField()),
                ("end_time", models.TimeField()),
                (
                    "room_label",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Free-text room if not using a registered venue.",
                        max_length=120,
                    ),
                ),
                (
                    "session_type",
                    models.CharField(
                        choices=[
                            ("lecture", "Lecture"),
                            ("tutorial", "Tutorial"),
                            ("practical", "Practical / Lab"),
                        ],
                        default="lecture",
                        max_length=20,
                    ),
                ),
                ("notes", models.CharField(blank=True, default="", max_length=255)),
                (
                    "is_published",
                    models.BooleanField(
                        default=True,
                        help_text="When false, hidden from student/lecturer portal views.",
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "course_unit",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="timetable_sessions",
                        to="Programs.courseunit",
                    ),
                ),
                (
                    "venue",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="timetable_sessions",
                        to="Programs.venue",
                    ),
                ),
            ],
            options={
                "verbose_name": "Timetable session",
                "verbose_name_plural": "Timetable sessions",
                "ordering": ["day_of_week", "start_time", "course_unit__code"],
            },
        ),
    ]
