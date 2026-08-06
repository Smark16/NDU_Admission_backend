from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0016_merge_20260805_2139"),
    ]

    operations = [
        migrations.AddField(
            model_name="scholarshipprogramme",
            name="sponsor_type",
            field=models.CharField(
                choices=[
                    ("state_house", "State House"),
                    ("hesfb", "HESFB"),
                    ("fawe", "FAWE"),
                    ("church", "Church sponsored"),
                    ("other", "Other / custom"),
                ],
                db_index=True,
                default="other",
                help_text="Taxonomy for State House, HESFB, FAWE, church, etc.",
                max_length=32,
            ),
        ),
    ]
