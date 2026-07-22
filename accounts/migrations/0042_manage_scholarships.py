# Generated manually for manage_scholarships ERP permission

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0041_rename_university_drop_steward"),
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
                        "Manage scholarship programmes, student awards, and fee waivers",
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
                ],
                "verbose_name": "ERP access policy",
                "verbose_name_plural": "ERP access policies",
            },
        ),
    ]
