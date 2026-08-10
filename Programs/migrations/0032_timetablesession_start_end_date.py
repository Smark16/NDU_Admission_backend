"""Add TimetableSession.start_date / end_date for recurring day-of-week slots."""

from django.db import migrations, models


def backfill_session_ranges(apps, schema_editor):
    TimetableSession = apps.get_model("Programs", "TimetableSession")
    for session in TimetableSession.objects.select_related(
        "course_unit__semester"
    ).iterator():
        if session.session_date:
            TimetableSession.objects.filter(pk=session.pk).update(
                start_date=session.session_date,
                end_date=session.session_date,
            )
            continue
        semester = getattr(getattr(session, "course_unit", None), "semester", None)
        if semester and semester.start_date:
            end = semester.end_date or semester.start_date
            TimetableSession.objects.filter(pk=session.pk).update(
                start_date=semester.start_date,
                end_date=end,
            )


class Migration(migrations.Migration):
    dependencies = [
        ("Programs", "0031_remove_study_groups"),
    ]

    operations = [
        migrations.AddField(
            model_name="timetablesession",
            name="start_date",
            field=models.DateField(
                blank=True,
                help_text="First date of the recurring period (inclusive).",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="timetablesession",
            name="end_date",
            field=models.DateField(
                blank=True,
                help_text="Last date of the recurring period (inclusive).",
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="timetablesession",
            name="session_date",
            field=models.DateField(
                blank=True,
                help_text=(
                    "One-off class date. Leave blank for a recurring slot that meets every "
                    "day_of_week between start_date and end_date."
                ),
                null=True,
            ),
        ),
        migrations.RunPython(backfill_session_ranges, migrations.RunPython.noop),
    ]
