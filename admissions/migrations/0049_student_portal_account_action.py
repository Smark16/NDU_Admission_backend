# Generated manually for StudentPortalAccountAction

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("admissions", "0048_exemption_change_requests"),
    ]

    operations = [
        migrations.CreateModel(
            name="StudentPortalAccountAction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "action",
                    models.CharField(
                        choices=[("deactivate", "Deactivate"), ("activate", "Activate")],
                        max_length=16,
                    ),
                ),
                ("reason", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "performed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="student_portal_account_actions_performed",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "portal_user",
                    models.ForeignKey(
                        blank=True,
                        help_text="The student login user that was toggled.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="student_portal_account_actions_as_subject",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "student",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="portal_account_actions",
                        to="admissions.admittedstudent",
                    ),
                ),
            ],
            options={
                "verbose_name": "Student portal account action",
                "verbose_name_plural": "Student portal account actions",
                "ordering": ["-created_at"],
            },
        ),
    ]
