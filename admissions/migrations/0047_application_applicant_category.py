from django.db import migrations, models


def backfill_applicant_category(apps, schema_editor):
    from admissions.applicant_category import category_from_nationality

    Application = apps.get_model("admissions", "Application")
    for app in Application.objects.all().iterator():
        app.applicant_category = category_from_nationality(app.nationality)
        app.save(update_fields=["applicant_category"])


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0046_application_refugee_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="application",
            name="applicant_category",
            field=models.CharField(
                choices=[("local", "Local"), ("international", "International")],
                default="local",
                max_length=20,
            ),
        ),
        migrations.RunPython(backfill_applicant_category, migrations.RunPython.noop),
    ]
