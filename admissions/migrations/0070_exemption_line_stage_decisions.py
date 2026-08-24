"""Per-paper Dean / AR decisions on exemption request lines."""

from django.db import migrations, models


def backfill_line_stage_decisions(apps, schema_editor):
    AdmissionChangeRequest = apps.get_model("admissions", "AdmissionChangeRequest")
    ExemptionRequestLine = apps.get_model("admissions", "ExemptionRequestLine")
    for req in AdmissionChangeRequest.objects.filter(change_type="exemption").iterator():
        lines = list(ExemptionRequestLine.objects.filter(change_request_id=req.id))
        for line in lines:
            updated = []
            if req.dean_status in ("approved", "rejected") and line.decision == "approved":
                line.dean_decision = "approved" if req.dean_status == "approved" else "rejected"
                updated.append("dean_decision")
            if req.ar_status in ("approved", "rejected") and line.decision == "approved":
                if req.dean_status != "rejected":
                    line.ar_decision = "approved" if req.ar_status == "approved" else "rejected"
                    updated.append("ar_decision")
            if updated:
                line.save(update_fields=updated)


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0069_exemption_review_stages"),
    ]

    operations = [
        migrations.AddField(
            model_name="exemptionrequestline",
            name="dean_decision",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("approved", "Approved"),
                    ("rejected", "Rejected"),
                ],
                db_index=True,
                default="pending",
                help_text="Faculty Dean approve/reject for this paper (after HOD).",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="exemptionrequestline",
            name="dean_decision_note",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Optional note when Dean rejects a paper.",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="exemptionrequestline",
            name="ar_decision",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("approved", "Approved"),
                    ("rejected", "Rejected"),
                ],
                db_index=True,
                default="pending",
                help_text="Academic Registrar approve/reject for this paper (after Dean).",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="exemptionrequestline",
            name="ar_decision_note",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Optional note when AR rejects a paper.",
                max_length=255,
            ),
        ),
        migrations.AlterField(
            model_name="exemptionrequestline",
            name="decision",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("approved", "Approved"),
                    ("rejected", "Rejected"),
                ],
                db_index=True,
                default="pending",
                help_text="HOD approve/reject for this paper.",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="exemptionrequestline",
            name="decision_note",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Optional note when HOD rejects a paper.",
                max_length=255,
            ),
        ),
        migrations.RunPython(backfill_line_stage_decisions, migrations.RunPython.noop),
    ]
