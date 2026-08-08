from django.db import migrations


def seed_bursar_scholarship_blocks(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    ct, _ = ContentType.objects.get_or_create(
        app_label="accounts",
        model="erpaccesspolicy",
    )
    for codename, name in (
        ("view_scholarships", "View scholarship programmes and sponsored student lists"),
        (
            "manage_scholarship_programmes",
            "Create, edit, and delete scholarship programmes",
        ),
        (
            "manage_scholarship_students",
            "Attach, bulk-upload, and remove students on scholarships",
        ),
    ):
        Permission.objects.get_or_create(
            content_type=ct,
            codename=codename,
            defaults={"name": name},
        )
    # Keep legacy full-access codename name in sync.
    Permission.objects.filter(
        content_type=ct, codename="manage_scholarships"
    ).update(name="Full scholarship access (all scholarship blocks)")

    from accounts.erp_role_setup import seed_erp_team_role_group

    seed_erp_team_role_group(Group, Permission, "Bursar")


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0046_scholarships_bursar_only"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="erpaccesspolicy",
            options={
                "default_permissions": (),
                "permissions": [
                    ("access_admissions", "Access Admissions module"),
                    (
                        "access_academics",
                        "Access Academics (programmes, curriculum, enrollment)",
                    ),
                    ("access_finance", "Access Finance and payments"),
                    ("access_reports", "Access Reports and analytics"),
                    ("access_user_management", "Access user administration"),
                    ("access_audit", "Access audit logs"),
                    ("access_system_settings", "Access academic and admission setup"),
                    ("access_lecturer_portal", "Access lecturer workspace"),
                    ("manage_direct_applications", "Manage direct-entry applications"),
                    (
                        "approve_admissions",
                        "Approve or reject applications and admissions",
                    ),
                    ("manage_batches", "Manage admission intakes and batches"),
                    ("assign_roles", "Assign Django groups to staff users"),
                    (
                        "manage_payment_reconciliation",
                        "Manage payment reconciliation tools",
                    ),
                    (
                        "post_manual_bank_payment",
                        "Post manual bank / reconciliation payments onto student tuition ledgers",
                    ),
                    (
                        "manage_curriculum",
                        "Manage programme curriculum (versions, mappings, inheritance)",
                    ),
                    (
                        "manage_program_scheduling",
                        "Manage cohort batches, semesters, and scheduled course offerings",
                    ),
                    ("manage_course_catalog", "Manage shared course catalog entries"),
                    (
                        "manage_academic_enrollment",
                        "Manage student programme enrollment and curriculum overrides",
                    ),
                    (
                        "configure_fee_plans",
                        "Configure fee plans, tuition matrices, and billing schedules",
                    ),
                    (
                        "manage_scholarships",
                        "Full scholarship access (all scholarship blocks)",
                    ),
                    (
                        "view_scholarships",
                        "View scholarship programmes and sponsored student lists",
                    ),
                    (
                        "manage_scholarship_programmes",
                        "Create, edit, and delete scholarship programmes",
                    ),
                    (
                        "manage_scholarship_students",
                        "Attach, bulk-upload, and remove students on scholarships",
                    ),
                    (
                        "manage_communication_templates",
                        "Manage system email templates and communications",
                    ),
                    (
                        "access_examinations",
                        "Access Examinations module (marks, timetable, publish, reports)",
                    ),
                    (
                        "access_graduation",
                        "Access Graduation module (qualified lists, ceremonies)",
                    ),
                    ("access_hostel", "Access Hostel / Halls of Residence module"),
                ],
                "verbose_name": "ERP access policy",
                "verbose_name_plural": "ERP access policies",
            },
        ),
        migrations.RunPython(seed_bursar_scholarship_blocks, noop_reverse),
    ]
