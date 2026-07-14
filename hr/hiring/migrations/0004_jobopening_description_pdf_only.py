# Generated manually for PDF-only job description validator

from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ("hiring", "0003_expand_application_field_lengths"),
    ]

    operations = [
        migrations.AlterField(
            model_name="jobopening",
            name="description",
            field=models.FileField(
                help_text="Upload the full job description as a PDF.",
                upload_to="job_descriptions/",
                validators=[
                    django.core.validators.FileExtensionValidator(allowed_extensions=["pdf"])
                ],
            ),
        ),
    ]
