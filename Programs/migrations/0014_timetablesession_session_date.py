from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("Programs", "0013_program_is_hec"),
    ]

    operations = [
        migrations.AddField(
            model_name="timetablesession",
            name="session_date",
            field=models.DateField(
                blank=True,
                help_text="Calendar date when this class takes place.",
                null=True,
            ),
        ),
    ]
