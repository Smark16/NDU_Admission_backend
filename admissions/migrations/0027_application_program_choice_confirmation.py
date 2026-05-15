from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0026_merge_20260515_0209"),
    ]

    operations = [
        migrations.AddField(
            model_name="application",
            name="program_choices_verification_sent_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When the applicant was asked to review/confirm programme choices (e.g. bulk email).",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="application",
            name="program_choices_confirmed_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When the applicant confirmed their programme choices in the portal.",
                null=True,
            ),
        ),
    ]
