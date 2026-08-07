from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("admissions", "0060_temporary_access_pass_verification_token"),
    ]

    operations = [
        migrations.AlterField(
            model_name="temporaryaccesspass",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending Bursar approval"),
                    ("active", "Active"),
                    ("revoked", "Revoked"),
                    ("expired", "Expired"),
                    ("rejected", "Rejected"),
                ],
                db_index=True,
                default="pending",
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="temporaryaccesspass",
            name="approved_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="temporaryaccesspass",
            name="approved_by",
            field=models.ForeignKey(
                blank=True,
                help_text="Bursar / Finance Manager who activated the pass.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="approved_temporary_access_passes",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterModelOptions(
            name="temporaryaccesspass",
            options={
                "ordering": ["-issued_at"],
                "permissions": [
                    (
                        "manage_temporary_access_pass",
                        "Can request, approve, and revoke temporary access passes",
                    )
                ],
                "verbose_name": "Temporary access pass",
                "verbose_name_plural": "Temporary access passes",
            },
        ),
    ]
