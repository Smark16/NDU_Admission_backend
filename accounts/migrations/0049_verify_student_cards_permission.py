# Add verify_student_cards ERP permission for Finance card scan desk

from django.apps import apps as django_apps
from django.contrib.auth.management import create_permissions
from django.contrib.contenttypes.management import create_contenttypes
from django.db import migrations


def ensure_permissions(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    app_config = django_apps.get_app_config("accounts")
    create_contenttypes(app_config, verbosity=0, interactive=False, using=db_alias)
    create_permissions(app_config, verbosity=0, interactive=False, using=db_alias)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0048_role_capability_matrix"),
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
                        "verify_student_cards",
                        "Verify student ID / registration cards (Finance card scan desk)",
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
                    (
                        "manage_role_capabilities",
                        "Manage role capability matrix (Allow / Deny permissions on roles)",
                    ),
                ],
                "verbose_name": "ERP access policy",
                "verbose_name_plural": "ERP access policies",
            },
        ),
        migrations.RunPython(ensure_permissions, noop),
    ]
