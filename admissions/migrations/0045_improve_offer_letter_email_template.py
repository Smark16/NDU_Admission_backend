from django.db import migrations


def sync_offer_letter_email_template(apps, schema_editor):
    from admissions.email_templates import EMAIL_TEMPLATE_DEFINITIONS

    EmailTemplate = apps.get_model("admissions", "EmailTemplate")
    key = "offer_letter_sent"
    row = EMAIL_TEMPLATE_DEFINITIONS[key]
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
        ("admissions", "0044_sync_email_template_branding"),
    ]

    operations = [
        migrations.RunPython(sync_offer_letter_email_template, migrations.RunPython.noop),
    ]
