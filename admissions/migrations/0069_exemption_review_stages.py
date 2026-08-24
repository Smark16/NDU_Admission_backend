"""Add multi-stage exemption review fields and backfill existing rows."""

from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


def backfill_exemption_stages(apps, schema_editor):
    AdmissionChangeRequest = apps.get_model("admissions", "AdmissionChangeRequest")
    qs = AdmissionChangeRequest.objects.filter(change_type="exemption")
    for req in qs.iterator():
        if req.status == "approved":
            req.hod_status = "approved"
            req.dean_status = "approved"
            req.ar_status = "approved"
            if req.reviewed_by_id:
                req.hod_reviewed_by_id = req.reviewed_by_id
                req.hod_reviewed_at = req.reviewed_at
                req.hod_notes = req.review_notes or ""
        elif req.status == "rejected":
            req.hod_status = "rejected"
            if req.reviewed_by_id:
                req.hod_reviewed_by_id = req.reviewed_by_id
                req.hod_reviewed_at = req.reviewed_at
                req.hod_notes = req.review_notes or ""
        req.save(
            update_fields=[
                "hod_status",
                "dean_status",
                "ar_status",
                "hod_reviewed_by",
                "hod_reviewed_at",
                "hod_notes",
            ]
        )


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0068_student_id_card_walk_in"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="admissionchangerequest",
            name="hod_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("approved", "Approved"),
                    ("rejected", "Rejected"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="admissionchangerequest",
            name="dean_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("approved", "Approved"),
                    ("rejected", "Rejected"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="admissionchangerequest",
            name="ar_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("approved", "Approved"),
                    ("rejected", "Rejected"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="admissionchangerequest",
            name="accounts_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("billed", "Billed"),
                    ("confirmed", "Confirmed"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="admissionchangerequest",
            name="hod_reviewed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="hod_reviewed_exemption_requests",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="admissionchangerequest",
            name="hod_reviewed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="admissionchangerequest",
            name="hod_notes",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="admissionchangerequest",
            name="dean_reviewed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="dean_reviewed_exemption_requests",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="admissionchangerequest",
            name="dean_reviewed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="admissionchangerequest",
            name="dean_notes",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="admissionchangerequest",
            name="ar_reviewed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="ar_reviewed_exemption_requests",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="admissionchangerequest",
            name="ar_reviewed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="admissionchangerequest",
            name="ar_notes",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="admissionchangerequest",
            name="accounts_reviewed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="accounts_reviewed_exemption_requests",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="admissionchangerequest",
            name="accounts_reviewed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="admissionchangerequest",
            name="accounts_notes",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AlterModelOptions(
            name="admissionchangerequest",
            options={
                "default_permissions": ("add", "change", "delete", "view"),
                "ordering": ["-created_at"],
                "permissions": [
                    (
                        "manage_admission_change_requests",
                        "Can approve or reject admission change requests (programme, campus, etc.)",
                    ),
                    (
                        "approve_exemption_requests",
                        "Can approve or reject course exemption change requests (HOD stage)",
                    ),
                    (
                        "review_exemption_dean",
                        "Can approve or reject course exemptions at Faculty Dean stage",
                    ),
                    (
                        "review_exemption_ar",
                        "Can approve or reject course exemptions at Academic Registrar stage",
                    ),
                    (
                        "bill_exemption_accounts",
                        "Can bill course exemption fees after AR approval",
                    ),
                ],
                "verbose_name": "Admission Change Request",
                "verbose_name_plural": "Admission Change Requests",
            },
        ),
        migrations.RunPython(backfill_exemption_stages, migrations.RunPython.noop),
        migrations.RunPython(
            code=lambda apps, schema_editor: _seed_exemption_stage_roles(apps),
            reverse_code=migrations.RunPython.noop,
        ),
    ]


def _seed_exemption_stage_roles(apps):
    """Refresh Dean + AR Data Clerk groups with new exemption stage permissions."""
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    try:
        from admissions.faculty_dean_role_setup import seed_faculty_dean_role

        seed_faculty_dean_role(Group, Permission)
    except Exception:
        pass
    try:
        from accounts.ar_data_clerk_role_setup import seed_ar_data_clerk_role

        seed_ar_data_clerk_role()
    except Exception:
        pass
