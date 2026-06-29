from django.db import migrations, models


def backfill_draft_applicant_category(apps, schema_editor):
    from admissions.applicant_category import category_from_nationality

    DraftApplication = apps.get_model("Drafts", "DraftApplication")
    for draft in DraftApplication.objects.all().iterator():
        draft.applicant_category = category_from_nationality(draft.nationality)
        draft.save(update_fields=["applicant_category"])


class Migration(migrations.Migration):

    dependencies = [
        ("Drafts", "0024_draftapplication_refugee_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="draftapplication",
            name="applicant_category",
            field=models.CharField(
                blank=True,
                choices=[("local", "Local"), ("international", "International")],
                default="local",
                max_length=20,
            ),
        ),
        migrations.RunPython(backfill_draft_applicant_category, migrations.RunPython.noop),
    ]
