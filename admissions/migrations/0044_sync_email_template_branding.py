from django.db import migrations


def sync_email_templates(apps, schema_editor):
    from admissions.email_templates import EMAIL_TEMPLATE_DEFINITIONS

    EmailTemplate = apps.get_model("admissions", "EmailTemplate")
    for key, row in EMAIL_TEMPLATE_DEFINITIONS.items():
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
        ("admissions", "0043_weekly_report_digest"),
    ]

    operations = [
        migrations.RunPython(sync_email_templates, migrations.RunPython.noop),
    ]
