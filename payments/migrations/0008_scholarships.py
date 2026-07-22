# Generated manually for scholarship programmes / awards / credits

import django.db.models.deletion
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0048_exemption_change_requests"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("payments", "0007_feeplanrule_billing_date"),
    ]

    operations = [
        migrations.AlterField(
            model_name="studenttuitionpayment",
            name="source",
            field=models.CharField(
                choices=[
                    ("scheduled", "Scheduled (semester fee)"),
                    ("ad_hoc", "Ad-hoc (individual charge)"),
                    ("scholarship", "Scholarship credit"),
                ],
                default="scheduled",
                max_length=12,
            ),
        ),
        migrations.CreateModel(
            name="ScholarshipProgramme",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=150)),
                ("code", models.CharField(help_text="Unique code e.g. STATE_HOUSE, HESFB, SPORTS", max_length=40, unique=True)),
                ("sponsor", models.CharField(blank=True, default="", max_length=150)),
                ("description", models.TextField(blank=True, default="")),
                ("fund_amount", models.DecimalField(blank=True, decimal_places=2, help_text="Optional programme ceiling. Null = no hard cap.", max_digits=14, null=True)),
                ("currency", models.CharField(default="UGX", max_length=3)),
                ("academic_year", models.CharField(blank=True, default="", help_text="e.g. 2025/2026", max_length=20)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_scholarship_programmes", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "Scholarship programme",
                "verbose_name_plural": "Scholarship programmes",
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="ScholarshipAward",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("award_amount", models.DecimalField(decimal_places=2, help_text="Maximum credit this student may receive from this award.", max_digits=14)),
                ("currency", models.CharField(default="UGX", max_length=3)),
                ("status", models.CharField(choices=[("active", "Active"), ("revoked", "Revoked"), ("exhausted", "Exhausted")], db_index=True, default="active", max_length=12)),
                ("notes", models.TextField(blank=True, default="")),
                ("applied_amount", models.DecimalField(decimal_places=2, default=Decimal("0"), help_text="Sum of active (non-reversed) scholarship credits posted.", max_digits=14)),
                ("awarded_at", models.DateTimeField(auto_now_add=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("awarded_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="issued_scholarship_awards", to=settings.AUTH_USER_MODEL)),
                ("programme", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="awards", to="payments.scholarshipprogramme")),
                ("revoked_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="revoked_scholarship_awards", to=settings.AUTH_USER_MODEL)),
                ("student", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="scholarship_awards", to="admissions.admittedstudent")),
            ],
            options={
                "verbose_name": "Scholarship award",
                "verbose_name_plural": "Scholarship awards",
                "ordering": ["-awarded_at"],
            },
        ),
        migrations.CreateModel(
            name="ScholarshipProgrammeWaiver",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("waiver_mode", models.CharField(choices=[("full", "Entire fee (100%)"), ("percent", "Percentage of fee")], default="full", max_length=10)),
                ("percent", models.DecimalField(blank=True, decimal_places=2, help_text="Required when waiver_mode=percent (e.g. 50.00).", max_digits=5, null=True)),
                ("fee_head", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="scholarship_programme_waivers", to="payments.feehead")),
                ("programme", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="default_waivers", to="payments.scholarshipprogramme")),
            ],
            options={
                "verbose_name": "Scholarship programme waiver",
                "verbose_name_plural": "Scholarship programme waivers",
                "ordering": ["fee_head__code"],
                "unique_together": {("programme", "fee_head")},
            },
        ),
        migrations.CreateModel(
            name="ScholarshipAwardWaiver",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("waiver_mode", models.CharField(choices=[("full", "Entire fee (100%)"), ("percent", "Percentage of fee")], default="full", max_length=10)),
                ("percent", models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ("award", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="waivers", to="payments.scholarshipaward")),
                ("fee_head", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="scholarship_award_waivers", to="payments.feehead")),
            ],
            options={
                "verbose_name": "Scholarship award waiver",
                "verbose_name_plural": "Scholarship award waivers",
                "ordering": ["fee_head__code"],
                "unique_together": {("award", "fee_head")},
            },
        ),
        migrations.CreateModel(
            name="ScholarshipCredit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=14)),
                ("currency", models.CharField(default="UGX", max_length=3)),
                ("applied_at", models.DateTimeField(auto_now_add=True)),
                ("is_reversed", models.BooleanField(default=False)),
                ("reversed_at", models.DateTimeField(blank=True, null=True)),
                ("notes", models.TextField(blank=True, default="")),
                ("applied_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="applied_scholarship_credits", to=settings.AUTH_USER_MODEL)),
                ("award", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="credits", to="payments.scholarshipaward")),
                ("fee_head", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="scholarship_credits", to="payments.feehead")),
                ("payment", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="scholarship_credit", to="payments.studenttuitionpayment")),
                ("reversed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reversed_scholarship_credits", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "Scholarship credit",
                "verbose_name_plural": "Scholarship credits",
                "ordering": ["-applied_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="scholarshipaward",
            constraint=models.UniqueConstraint(
                condition=models.Q(status="active"),
                fields=("programme", "student"),
                name="uniq_active_scholarship_award_per_student",
            ),
        ),
    ]
