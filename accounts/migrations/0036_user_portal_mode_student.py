from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0035_user_portal_mode"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="portal_mode",
            field=models.CharField(
                blank=True,
                choices=[
                    ("admin", "Admin portal"),
                    ("lecturer", "Lecturer portal"),
                    ("student", "Student portal"),
                ],
                help_text="Active portal view when the user can access more than one ERP portal.",
                max_length=20,
                null=True,
            ),
        ),
    ]
