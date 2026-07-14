from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("Programs", "0014_timetablesession_session_date"),
        ("admissions", "0041_faculty_admin_batch_classroom_perms"),
    ]

    operations = [
        migrations.AddField(
            model_name="admittedstudent",
            name="admitted_specialization",
            field=models.ForeignKey(
                blank=True,
                help_text="Teaching subject combination / programme track selected at admission (required for programmes with has_specialization=True).",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="admitted_students",
                to="Programs.programspecialization",
            ),
        ),
    ]
