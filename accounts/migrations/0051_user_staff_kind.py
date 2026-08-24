from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0050_active_staff_id_card_template"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="staff_kind",
            field=models.CharField(
                choices=[("FULL_TIME", "Full-time"), ("PART_TIME", "Part-time")],
                db_index=True,
                default="FULL_TIME",
                help_text=(
                    "Full-time staff log in with email; part-time staff log in with a username "
                    "(email is still captured for communication)."
                ),
                max_length=20,
            ),
        ),
    ]
