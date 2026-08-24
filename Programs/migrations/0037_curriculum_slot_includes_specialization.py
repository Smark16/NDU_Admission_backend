# Allow same catalog course on multiple subject combinations (tracks)
# at the same year/term. Unique key now includes specialization.

from django.db import migrations, models


def normalize_null_specialization(apps, schema_editor):
    Line = apps.get_model("Programs", "ProgramCurriculumLine")
    Line.objects.filter(specialization__isnull=True).update(specialization="")


class Migration(migrations.Migration):

    dependencies = [
        ("Programs", "0036_sharedteachingoffering_parent_course_unit"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="programcurriculumline",
            name="unique_curriculum_slot",
        ),
        migrations.RunPython(normalize_null_specialization, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="programcurriculumline",
            name="specialization",
            field=models.CharField(
                blank=True,
                default="",
                help_text=(
                    "Track / subject combination this line belongs to "
                    "(e.g. 'Mathematics and Physics'). Blank = shared by all tracks."
                ),
                max_length=100,
            ),
        ),
        migrations.AddConstraint(
            model_name="programcurriculumline",
            constraint=models.UniqueConstraint(
                fields=(
                    "curriculum_version",
                    "catalog_course",
                    "year_of_study",
                    "term_number",
                    "specialization",
                ),
                name="unique_curriculum_slot",
            ),
        ),
    ]
