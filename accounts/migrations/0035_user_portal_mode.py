from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0034_finance_officer_student_access"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="portal_mode",
            field=models.CharField(
                blank=True,
                choices=[("admin", "Admin portal"), ("lecturer", "Lecturer portal")],
                help_text="Active ERP portal view when the user has more than one role (admin + lecturer).",
                max_length=20,
                null=True,
            ),
        ),
    ]
