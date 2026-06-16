from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0036_alter_application_program_choices_confirmed_at"),
        ("accounts", "0032_systemsettings_portal_branding"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="faculties",
            field=models.ManyToManyField(
                blank=True,
                help_text="Faculties this staff member may access (Faculty Dean and similar roles).",
                related_name="assigned_staff",
                to="admissions.faculty",
            ),
        ),
    ]
