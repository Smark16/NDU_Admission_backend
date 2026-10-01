# Generated manually for Zimbra Admin SOAP integration config

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("integrations", "0002_moodle_launch_signing_secret"),
    ]

    operations = [
        migrations.CreateModel(
            name="ZimbraIntegrationConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_enabled", models.BooleanField(default=False)),
                (
                    "admin_soap_url",
                    models.URLField(
                        blank=True,
                        default="https://ndejjemail.ndu.ac.ug:7071/service/admin/soap",
                        help_text="Zimbra Admin SOAP endpoint.",
                    ),
                ),
                ("admin_username", models.CharField(blank=True, default="", max_length=255)),
                (
                    "admin_password",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Admin password for SOAP auth. Never returned by the API.",
                        max_length=255,
                    ),
                ),
                ("domain", models.CharField(blank=True, default="educ.ndu.ac.ug", max_length=255)),
                (
                    "default_password",
                    models.CharField(
                        blank=True,
                        default="NduStudent#2026",
                        help_text="Temporary mailbox password; paired with zimbraPasswordMustChange.",
                        max_length=128,
                    ),
                ),
                (
                    "verify_ssl",
                    models.BooleanField(
                        default=True,
                        help_text="Verify TLS certificates when calling the Admin SOAP URL.",
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Zimbra integration config",
                "verbose_name_plural": "Zimbra integration config",
            },
        ),
    ]
