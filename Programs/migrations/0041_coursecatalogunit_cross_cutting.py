from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("Programs", "0040_program_modular_calendar"),
    ]

    operations = [
        migrations.AddField(
            model_name="coursecatalogunit",
            name="is_cross_cutting",
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text=(
                    "True when this paper commonly runs as one sitting across programmes/faculties "
                    "(Ethics, Comm Skills, CISCO, Literacy, etc.). Programme CourseUnits stay separate; "
                    "use Shared Teaching when they share time/room/lecturer."
                ),
            ),
        ),
        migrations.AddField(
            model_name="coursecatalogunit",
            name="cross_cutting_note",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Optional hint for staff (e.g. often shared Main Day + Weekend).",
                max_length=255,
            ),
        ),
    ]
