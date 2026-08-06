# Generated manually — building-relative floor band semantics

from django.db import migrations, models


def reset_band_counts_to_one(apps, schema_editor):
    """Old defaults were absolute thresholds (3/2); new meaning is top/bottom count."""
    Hostel = apps.get_model("hostel", "Hostel")
    Hostel.objects.all().update(
        fresher_min_sort_order=1,
        continuing_max_sort_order=1,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("hostel", "0004_hostel_floor_band_settings"),
    ]

    operations = [
        migrations.AlterField(
            model_name="hostel",
            name="fresher_min_sort_order",
            field=models.PositiveSmallIntegerField(
                default=1,
                help_text=(
                    "How many of the highest floors in each hall to suggest for freshers "
                    "(1 = only the top level of that building)."
                ),
            ),
        ),
        migrations.AlterField(
            model_name="hostel",
            name="continuing_max_sort_order",
            field=models.PositiveSmallIntegerField(
                default=1,
                help_text=(
                    "How many of the lowest floors in each hall to suggest for continuing "
                    "students (1 = only the ground/lowest level of that building)."
                ),
            ),
        ),
        migrations.RunPython(reset_band_counts_to_one, migrations.RunPython.noop),
    ]
