from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("Programs", "0009_roomtype_and_venue_code"),
    ]

    operations = [
        migrations.AddField(
            model_name="venue",
            name="allows_parallel_sessions",
            field=models.BooleanField(
                default=False,
                help_text="When true, multiple practical/lab sessions may use this room at the same time (split groups).",
            ),
        ),
        migrations.AddField(
            model_name="timetablesession",
            name="delivery_mode",
            field=models.CharField(
                choices=[
                    ("on_campus", "On campus"),
                    ("online", "Online"),
                    ("hybrid", "Hybrid"),
                ],
                default="on_campus",
                help_text="Online sessions skip room clash checks; hybrid/on_campus use registered rooms when published.",
                max_length=20,
            ),
        ),
    ]
