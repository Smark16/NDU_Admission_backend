# Generated manually for ManualBankPaymentChangeRequest

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0050_admitted_bonafide_list_idx"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("payments", "0011_student_fee_exemption"),
    ]

    operations = [
        migrations.CreateModel(
            name="ManualBankPaymentChangeRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("request_type", models.CharField(choices=[("post", "Post payment"), ("update", "Edit payment"), ("delete", "Delete payment")], max_length=16)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected"), ("cancelled", "Cancelled")], db_index=True, default="pending", max_length=16)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("reason", models.TextField(blank=True, help_text="Required for edit and delete requests.")),
                ("requested_at", models.DateTimeField(auto_now_add=True)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("review_notes", models.TextField(blank=True)),
                ("ledger", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="change_requests", to="payments.tuitionledger")),
                ("requested_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="manual_bank_requests_made", to=settings.AUTH_USER_MODEL)),
                ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="manual_bank_requests_reviewed", to=settings.AUTH_USER_MODEL)),
                ("student", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="manual_bank_change_requests", to="admissions.admittedstudent")),
            ],
            options={
                "ordering": ["-requested_at"],
            },
        ),
        migrations.AddIndex(
            model_name="manualbankpaymentchangerequest",
            index=models.Index(fields=["status", "-requested_at"], name="payments_ma_status_7a0b1c_idx"),
        ),
    ]
