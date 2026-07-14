from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0031_merge_20260605_2251"),
    ]

    operations = [
        migrations.AddField(
            model_name="systemsettings",
            name="university_name",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Display name on login and portal headers (e.g. NDEJJE UNIVERSITY STEWARD ERP).",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="systemsettings",
            name="portal_logo",
            field=models.ImageField(
                blank=True,
                help_text="Logo shown on the login page and optionally elsewhere in the portal.",
                null=True,
                upload_to="portal_branding/",
            ),
        ),
        migrations.AddField(
            model_name="systemsettings",
            name="login_cover_image",
            field=models.ImageField(
                blank=True,
                help_text="Hero / background image on the login page left panel.",
                null=True,
                upload_to="portal_branding/",
            ),
        ),
    ]
