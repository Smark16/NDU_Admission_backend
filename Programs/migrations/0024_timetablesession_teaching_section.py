# TimetableSession.teaching_section for section-aware scheduling

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("Programs", "0023_teaching_section"),
    ]

    operations = [
        migrations.AddField(
            model_name="timetablesession",
            name="teaching_section",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Null = whole cohort (shared lecture). Set to a teaching section for "
                    "section-only tutorials/labs/parallel streams. Same lecturers may teach "
                    "multiple section sessions on the same course unit."
                ),
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="timetable_sessions",
                to="Programs.teachingsection",
            ),
        ),
    ]
