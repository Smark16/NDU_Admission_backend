from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("staff", "0003_widen_department_names"),
    ]

    operations = [
        migrations.AlterField(
            model_name="staffprofile",
            name="job_title",
            field=models.CharField(blank=True, max_length=120, null=True),
        ),
        migrations.CreateModel(
            name="StaffIdCard",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("card_number", models.CharField(db_index=True, max_length=48, unique=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("generated", "Generated"),
                            ("printed", "Printed"),
                            ("active", "Active"),
                            ("revoked", "Revoked"),
                            ("reissued", "Reissued"),
                        ],
                        default="generated",
                        max_length=20,
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(
                        default=True,
                        help_text="False when revoked or superseded by a reissue.",
                    ),
                ),
                ("issue_date", models.DateField()),
                ("expiry_date", models.DateField(blank=True, null=True)),
                ("print_count", models.PositiveIntegerField(default=0)),
                ("revoke_reason", models.TextField(blank=True, default="")),
                ("reissue_reason", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "issued_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="issued_staff_id_cards",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "replaced_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="supersedes",
                        to="staff.staffidcard",
                    ),
                ),
                (
                    "staff_profile",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="id_cards",
                        to="staff.staffprofile",
                    ),
                ),
            ],
            options={
                "verbose_name": "Staff ID card",
                "verbose_name_plural": "Staff ID cards",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="staffidcard",
            index=models.Index(fields=["staff_profile", "is_active"], name="staff_staff_staff_p_8c1a2f_idx"),
        ),
        migrations.AddIndex(
            model_name="staffidcard",
            index=models.Index(fields=["status"], name="staff_staff_status_9d4b11_idx"),
        ),
    ]
