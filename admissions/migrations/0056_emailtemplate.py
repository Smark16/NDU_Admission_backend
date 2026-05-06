from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def seed_email_templates(apps, schema_editor):
    EmailTemplate = apps.get_model("admissions", "EmailTemplate")
    defaults = {
        "application_submitted": {
            "name": "Application Submitted",
            "description": "Sent immediately after a successful application submission.",
            "subject_template": "Application Submitted Successfully!",
            "body_template_html": (
                "Dear {{full_name}},<br/><br/>"
                "Your application has been successfully submitted to Ndejje University.<br/>"
                "Application ID: {{application_id}}<br/>"
                "Submitted on: {{submitted_date}}<br/><br/>"
                "Thank you,<br/>Ndejje University Admissions Team"
            ),
        },
        "admission_accepted": {
            "name": "Admission Accepted",
            "description": "Sent when a student is admitted.",
            "subject_template": "Congratulations! You have been admitted to Ndejje University",
            "body_template_html": (
                "Dear {{full_name}},<br/><br/>"
                "<strong>CONGRATULATIONS!</strong><br/><br/>"
                "We are delighted to inform you that your application has been successfully reviewed and ACCEPTED.<br/><br/>"
                "You have been offered admission to study:<br/>"
                "- Program: {{program}}<br/>"
                "- Campus: {{campus}}<br/>"
                "- Study Mode: {{study_mode}}<br/>"
                "- Batch: {{batch_name}} ({{academic_year}})<br/><br/>"
                "Your provisional admission letter will be sent shortly.<br/><br/>"
                "We look forward to welcoming you!<br/><br/>"
                "Admissions Office<br/>Ndejje University"
            ),
        },
        "admission_updated": {
            "name": "Admission Updated",
            "description": "Sent when an admitted student record is updated.",
            "subject_template": "Admission updated Successfully",
            "body_template_html": (
                "Dear {{full_name}},<br/><br/>"
                "Your admission has been updated.<br/><br/>"
                "Student Number: {{student_id}}<br/>"
                "Registration Number: {{reg_no}}<br/>"
                "Program: {{program}}<br/>"
                "Campus: {{campus}}<br/><br/>"
                "If you did not expect this email, please ignore it."
            ),
        },
        "offer_letter_sent": {
            "name": "Offer Letter Sent",
            "description": "Sent when an offer/admission letter is made available in portal.",
            "subject_template": "Admission letter sent successfully",
            "body_template_html": (
                "Dear {{full_name_upper}},<br/><br/>"
                "<strong>CONGRATULATIONS!</strong><br/><br/>"
                "We are delighted to inform you that your admission letter has been successfully sent to your portal.<br/><br/>"
                "Next Steps:<br/>"
                "1. Log in to your portal to download your official admission letter<br/>"
                "2. Confirm everything is ok and sign where necessary<br/>"
                "3. Complete registration before the deadline<br/><br/>"
                "We look forward to welcoming you to the Ndejje University family!<br/><br/>"
                "Warm regards,<br/>Admissions Office<br/>Ndejje University<br/>"
                "Email: admissions@ndejjeuniversity.ac.ug<br/>"
                "Website: www.ndejjeuniversity.ac.ug"
            ),
        },
    }
    for key, row in defaults.items():
        EmailTemplate.objects.update_or_create(
            key=key,
            defaults={
                "name": row["name"],
                "description": row["description"],
                "subject_template": row["subject_template"],
                "body_template_html": row["body_template_html"],
                "is_active": True,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("admissions", "0055_admittedstudent_schoolpay_code"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="EmailTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "key",
                    models.CharField(
                        choices=[
                            ("application_submitted", "Application Submitted"),
                            ("admission_accepted", "Admission Accepted"),
                            ("admission_updated", "Admission Updated"),
                            ("offer_letter_sent", "Offer Letter Sent"),
                        ],
                        max_length=80,
                        unique=True,
                    ),
                ),
                ("name", models.CharField(max_length=160)),
                ("description", models.TextField(blank=True)),
                ("subject_template", models.CharField(max_length=255)),
                ("body_template_html", models.TextField()),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="updated_email_templates",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Email Template",
                "verbose_name_plural": "Email Templates",
                "ordering": ["name"],
            },
        ),
        migrations.RunPython(seed_email_templates, migrations.RunPython.noop),
    ]

