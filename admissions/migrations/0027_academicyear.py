# Generated manually for academic year registry

from django.db import migrations, models


def seed_academic_years(apps, schema_editor):
    AcademicYear = apps.get_model("admissions", "AcademicYear")
    Batch = apps.get_model("admissions", "Batch")
    ProgramBatch = apps.get_model("Programs", "ProgramBatch")

    labels = set()
    for raw in Batch.objects.exclude(academic_year="").values_list("academic_year", flat=True):
        text = (raw or "").strip().replace("-", "/")
        if len(text) >= 9 and "/" in text:
            labels.add(text)
    for raw in ProgramBatch.objects.exclude(academic_year="").values_list(
        "academic_year", flat=True
    ):
        text = (raw or "").strip().replace("-", "/")
        if len(text) >= 9 and "/" in text:
            labels.add(text)

    # Calendar default
    from datetime import date

    today = date.today()
    year = today.year
    if today.month >= 8:
        labels.add(f"{year}/{year + 1}")
    else:
        labels.add(f"{year - 1}/{year}")

    current_label = max(labels) if labels else f"{year - 1}/{year}"
    for label in sorted(labels):
        AcademicYear.objects.get_or_create(
            label=label,
            defaults={"is_active": True, "is_current": label == current_label},
        )


class Migration(migrations.Migration):

    dependencies = [
       ("admissions", "0024_application_programs"),
    ]

    operations = [
        migrations.CreateModel(
            name="AcademicYear",
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
                ("label", models.CharField(max_length=25, unique=True)),
                (
                    "is_current",
                    models.BooleanField(
                        default=False,
                        help_text="Default year suggested when creating new batches.",
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(
                        default=True,
                        help_text="Inactive years stay on old records but cannot be selected for new batches.",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Academic year",
                "verbose_name_plural": "Academic years",
                "ordering": ["-label"],
            },
        ),
        migrations.RunPython(seed_academic_years, migrations.RunPython.noop),
    ]
