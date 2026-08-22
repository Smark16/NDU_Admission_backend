from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("Programs", "0035_shared_teaching_offering"),
    ]

    operations = [
        migrations.AddField(
            model_name="sharedteachingoffering",
            name="parent_course_unit",
            field=models.ForeignKey(
                blank=True,
                help_text="Canonical programme offering for this shared class (Moodle parent_unit_id and shared_unit_key). Set from Timetable when linking cross-cutting programmes.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="shared_teaching_as_parent",
                to="Programs.courseunit",
            ),
        ),
    ]
