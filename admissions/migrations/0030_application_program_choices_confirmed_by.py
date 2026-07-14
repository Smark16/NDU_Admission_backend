from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0024_application_programs"),
    ]

    operations = [
        migrations.AddField(
            model_name="application",
            name="program_choices_confirmed_by",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Who confirmed: applicant (portal) or staff (change programme). Empty = legacy.",
                max_length=16,
            ),
        ),
    ]
