# Default admission batch scope for bursar weekly report

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0050_admitted_bonafide_list_idx"),
        ("payments", "0012_manual_bank_payment_change_request"),
    ]

    operations = [
        migrations.AddField(
            model_name="bursarweeklyreportsettings",
            name="report_batch",
            field=models.ForeignKey(
                blank=True,
                help_text="Default admission batch/intake for scheduled and default report scope.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="admissions.batch",
            ),
        ),
    ]
