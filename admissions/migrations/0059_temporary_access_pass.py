from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("admissions", "0058_exemption_line_decision"),
        ("payments", "0015_rename_payments_ma_status_7a0b1c_idx_payments_ma_status_b6f60e_idx_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="TemporaryAccessPass",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "sponsor_type",
                    models.CharField(
                        choices=[
                            ("state_house", "State House"),
                            ("hesfb", "HESFB"),
                            ("fawe", "FAWE"),
                            ("church", "Church sponsored"),
                            ("other", "Other / custom"),
                        ],
                        db_index=True,
                        default="other",
                        max_length=32,
                    ),
                ),
                ("sponsor_label", models.CharField(blank=True, default="", help_text="Display name, e.g. parish or custom sponsor.", max_length=150)),
                ("reason", models.CharField(blank=True, default="", max_length=255)),
                ("notes", models.TextField(blank=True, default="")),
                ("allow_lectures", models.BooleanField(default=True, help_text="Temporary permission to attend lectures / classes.")),
                ("allow_hostel", models.BooleanField(default=False, help_text="Accounts-approved temporary hostel access.")),
                ("allow_meals", models.BooleanField(default=False, help_text="Accounts-approved temporary meals access.")),
                ("allow_registration", models.BooleanField(default=False, help_text="Must remain False. Registration requires full Accounts clearance.")),
                ("allow_documents", models.BooleanField(default=False, help_text="Must remain False. Official docs require full clearance.")),
                ("valid_from", models.DateField(default=django.utils.timezone.localdate)),
                ("valid_until", models.DateField(blank=True, help_text="Inclusive end date. Null = until revoked.", null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("active", "Active"),
                            ("revoked", "Revoked"),
                            ("expired", "Expired"),
                        ],
                        db_index=True,
                        default="active",
                        max_length=12,
                    ),
                ),
                ("issued_at", models.DateTimeField(auto_now_add=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("revoke_reason", models.CharField(blank=True, default="", max_length=255)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "issued_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="issued_temporary_access_passes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "revoked_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="revoked_temporary_access_passes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "scholarship_award",
                    models.ForeignKey(
                        blank=True,
                        help_text="Optional link to the scholarship award this pass supports.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="temporary_access_passes",
                        to="payments.scholarshipaward",
                    ),
                ),
                (
                    "student",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="temporary_access_passes",
                        to="admissions.admittedstudent",
                    ),
                ),
            ],
            options={
                "verbose_name": "Temporary access pass",
                "verbose_name_plural": "Temporary access passes",
                "ordering": ["-issued_at"],
                "permissions": [
                    ("manage_temporary_access_pass", "Can issue and revoke temporary access passes"),
                ],
            },
        ),
        migrations.AddIndex(
            model_name="temporaryaccesspass",
            index=models.Index(fields=["student", "status"], name="admissions__student_b8e2a1_idx"),
        ),
        migrations.AddIndex(
            model_name="temporaryaccesspass",
            index=models.Index(fields=["status", "valid_until"], name="admissions__status_9c4d2f_idx"),
        ),
    ]
