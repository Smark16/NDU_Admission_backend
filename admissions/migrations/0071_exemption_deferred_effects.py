# Generated manually — defer exemption curriculum/promotion until AR approval.

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.utils import timezone


def mark_existing_ar_approved_as_applied(apps, schema_editor):
    AdmissionChangeRequest = apps.get_model("admissions", "AdmissionChangeRequest")
    now = timezone.now()
    AdmissionChangeRequest.objects.filter(
        change_type="exemption",
        ar_status="approved",
        exemption_effects_applied_at__isnull=True,
    ).update(exemption_effects_applied_at=now)


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0070_exemption_line_stage_decisions"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="admissionchangerequest",
            name="exemption_promotion_year",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="admissionchangerequest",
            name="exemption_promotion_term",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="admissionchangerequest",
            name="exemption_promotion_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="proposed_exemption_promotions",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="admissionchangerequest",
            name="exemption_promotion_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="admissionchangerequest",
            name="exemption_effects_applied_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When curriculum exemptions and promotion were applied to the student record.",
                null=True,
            ),
        ),
        migrations.RunPython(mark_existing_ar_approved_as_applied, migrations.RunPython.noop),
    ]
