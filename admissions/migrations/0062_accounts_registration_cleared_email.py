from django.db import migrations, models


def seed_accounts_cleared_template(apps, schema_editor):
    from admissions.email_templates import EMAIL_TEMPLATE_DEFINITIONS

    EmailTemplate = apps.get_model("admissions", "EmailTemplate")
    key = "accounts_registration_cleared"
    row = EMAIL_TEMPLATE_DEFINITIONS.get(key)
    if not row:
        return
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
        ("admissions", "0061_temporary_access_pass_bursar_approval"),
    ]

    operations = [
        migrations.AlterField(
            model_name="emailtemplate",
            name="key",
            field=models.CharField(
                choices=[
                    ("application_submitted", "Application Submitted"),
                    ("admission_accepted", "Admission Accepted"),
                    ("admission_updated", "Admission Updated"),
                    ("offer_letter_sent", "Offer Letter Sent"),
                    ("weekly_admissions_digest", "Weekly Admissions Digest"),
                    ("accounts_registration_cleared", "Accounts Registration Cleared"),
                ],
                max_length=80,
                unique=True,
            ),
        ),
        migrations.RunPython(seed_accounts_cleared_template, migrations.RunPython.noop),
    ]
