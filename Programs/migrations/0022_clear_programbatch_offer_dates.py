from django.db import migrations


def clear_cohort_offer_dates(apps, schema_editor):
    ProgramBatch = apps.get_model("Programs", "ProgramBatch")
    ProgramBatch.objects.exclude(
        offer_start_date=None, offer_end_date=None
    ).update(offer_start_date=None, offer_end_date=None)


def noop_reverse(apps, schema_editor):
    # Cannot restore cleared dates.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("Programs", "0019_course_material"),
    ]

    operations = [
        migrations.RunPython(clear_cohort_offer_dates, noop_reverse),
    ]
