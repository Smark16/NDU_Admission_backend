from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0055_seed_hod_role"),
    ]

    operations = [
        migrations.AlterField(
            model_name="studentportalaccountaction",
            name="action",
            field=models.CharField(
                choices=[
                    ("deactivate", "Deactivate"),
                    ("activate", "Activate"),
                    ("reset_password", "Reset password"),
                ],
                max_length=16,
            ),
        ),
    ]
