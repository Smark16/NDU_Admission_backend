from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0064_merge_academic_department_branches"),
    ]

    operations = [
        migrations.AddField(
            model_name="admittedstudent",
            name="exemption_form_draft",
            field=models.JSONField(
                blank=True,
                help_text="In-progress Course Exemption form so staff can view/submit after the 50k fee is paid.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="admittedstudent",
            name="exemption_form_draft_updated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
