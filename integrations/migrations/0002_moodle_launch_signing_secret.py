# Generated manually for Moodle SSO launch signing secret

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("integrations", "0001_moodle_integration_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="moodleintegrationconfig",
            name="launch_signing_secret",
            field=models.CharField(
                blank=True,
                default="",
                help_text=(
                    "Shared secret for STEWARD→Moodle SSO launch HMAC "
                    "(same value Moodle uses to verify sig). Set automatically when rotating the API key."
                ),
                max_length=255,
            ),
        ),
    ]
