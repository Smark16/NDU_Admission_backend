from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0015_rename_payments_ma_status_7a0b1c_idx_payments_ma_status_b6f60e_idx_and_more"),
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
