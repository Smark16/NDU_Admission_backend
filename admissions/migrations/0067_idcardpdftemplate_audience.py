from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0066_accounts_hostel_cleared"),
    ]

    operations = [
        migrations.AddField(
            model_name="idcardpdftemplate",
            name="audience",
            field=models.CharField(
                choices=[("student", "Student ID"), ("staff", "Staff ID")],
                db_index=True,
                default="student",
                help_text="Whether this blank is used for student or staff cards.",
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="idcardpdftemplate",
            name="key",
            field=models.SlugField(
                help_text="Stable key; must match SystemSettings.active_id_card_template or active_staff_id_card_template.",
                max_length=80,
                unique=True,
            ),
        ),
    ]
