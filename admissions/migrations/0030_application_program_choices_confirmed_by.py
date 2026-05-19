from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0029_merge_20260515_1550"),
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
