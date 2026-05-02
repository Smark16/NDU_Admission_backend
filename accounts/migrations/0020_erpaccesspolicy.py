from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0019_user_is_lecturer_user_is_student_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ErpAccessPolicy",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("label", models.CharField(default="default", editable=False, max_length=64, unique=True)),
            ],
            options={
                "verbose_name": "ERP access policy",
                "verbose_name_plural": "ERP access policies",
                "default_permissions": (),
                "permissions": (
                    ("access_admissions", "Access Admissions module"),
                    ("access_academics", "Access Academics (programmes, curriculum, enrollment)"),
                    ("access_finance", "Access Finance and payments"),
                    ("access_reports", "Access Reports and analytics"),
                    ("access_user_management", "Access user administration"),
                    ("access_audit", "Access audit logs"),
                    ("access_system_settings", "Access academic and admission setup"),
                    ("access_lecturer_portal", "Access lecturer workspace"),
                    ("manage_direct_applications", "Manage direct-entry applications"),
                    ("approve_admissions", "Approve or reject applications and admissions"),
                    ("manage_batches", "Manage admission intakes and batches"),
                    ("assign_roles", "Assign Django groups to staff users"),
                    ("manage_payment_reconciliation", "Manage payment reconciliation tools"),
                ),
            },
        ),
    ]
