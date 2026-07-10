from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("staff", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="PayScale",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(help_text="Scale code, e.g. U7 or P2", max_length=10, unique=True)),
                ("name", models.CharField(max_length=200)),
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("ACADEMIC", "Academic"),
                            ("ADMINISTRATIVE", "Administrative"),
                            ("SUPPORT", "Support"),
                        ],
                        default="ADMINISTRATIVE",
                        max_length=20,
                    ),
                ),
                (
                    "rank_order",
                    models.PositiveSmallIntegerField(
                        default=0,
                        help_text="Lower numbers = junior grades (used for sorting)",
                    ),
                ),
                ("description", models.TextField(blank=True)),
                (
                    "typical_roles",
                    models.CharField(
                        blank=True,
                        help_text="Example job titles commonly placed on this scale",
                        max_length=500,
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Pay scale",
                "verbose_name_plural": "Pay scales",
                "ordering": ["rank_order", "code"],
            },
        ),
        migrations.AddField(
            model_name="staffprofile",
            name="pay_scale",
            field=models.ForeignKey(
                blank=True,
                help_text="Ugandan salary scale (U/P grade) per IPPS-style grading",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="staff_profiles",
                to="staff.payscale",
            ),
        ),
        migrations.AddField(
            model_name="staffprofile",
            name="pay_step",
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text="Salary step/notch on the scale (typically 1–35)",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="staffcontract",
            name="pay_scale",
            field=models.ForeignKey(
                blank=True,
                help_text="Contracted Ugandan pay scale (U/P grade)",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="contracts",
                to="staff.payscale",
            ),
        ),
        migrations.AddField(
            model_name="staffcontract",
            name="pay_step",
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text="Salary step/notch on the scale",
                null=True,
            ),
        ),
    ]
