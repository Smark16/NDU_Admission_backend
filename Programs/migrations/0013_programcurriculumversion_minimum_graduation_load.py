from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("Programs", "0012_coursecatalogunit_program_calendar_type_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="programcurriculumversion",
            name="minimum_graduation_load",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text=(
                    "Optional minimum total credit units for this curriculum version. "
                    "When null, the programme's Program.minimum_graduation_load is used."
                ),
                max_digits=6,
                null=True,
            ),
        ),
    ]
