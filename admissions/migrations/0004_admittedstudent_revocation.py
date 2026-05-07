from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
        ("admissions", "0003_application_school_pay_reference"),
    ]

    operations = [
        migrations.AddField(
            model_name="admittedstudent",
            name="is_revoked",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="admittedstudent",
            name="revocation_reason",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="admittedstudent",
            name="revoked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="admittedstudent",
            name="revoked_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="revoked_admissions",
                to="accounts.user",
            ),
        ),
        migrations.AlterModelOptions(
            name="admittedstudent",
            options={
                "ordering": ["-admission_date"],
                "permissions": [
                    ("verify_physical_documents", "Can verify physical admission documents"),
                    ("revoke_admission", "Can revoke admitted students"),
                ],
                "verbose_name": "Admitted Student",
                "verbose_name_plural": "Admitted Students",
            },
        ),
    ]
