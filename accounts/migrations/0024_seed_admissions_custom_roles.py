from django.apps import apps as django_apps
from django.contrib.auth.management import create_permissions
from django.contrib.contenttypes.management import create_contenttypes
from django.db import migrations


def _get_permission(Permission, app_label: str, codename: str):
    perm = Permission.objects.filter(content_type__app_label=app_label, codename=codename).first()
    if perm:
        return perm
    perm = Permission.objects.filter(content_type__app_label=app_label.lower(), codename=codename).first()
    if perm:
        return perm
    return Permission.objects.filter(codename=codename).first()


def seed_admissions_custom_roles(apps, schema_editor):
    db_alias = schema_editor.connection.alias

    # Ensure permissions exist for all involved apps.
    for app_name in ("accounts", "admissions", "AdmissionReports", "payments", "audit", "Programs"):
        app_config = django_apps.get_app_config(app_name)
        create_contenttypes(app_config, verbosity=0, interactive=False, using=db_alias)
        create_permissions(app_config, verbosity=0, interactive=False, using=db_alias)

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    # (app_label, codename)
    matrix = {
        "Admissions Reviewer": [
            ("admissions", "view_application"),
            ("admissions", "change_application"),
            ("admissions", "view_admittedstudent"),
            ("admissions", "view_batch"),
            ("admissions", "view_faculty"),
            ("admissions", "view_academiclevel"),
        ],
        "Admissions Approver": [
            ("admissions", "view_application"),
            ("admissions", "change_application"),
            ("admissions", "add_admittedstudent"),
            ("admissions", "change_admittedstudent"),
            ("admissions", "view_admittedstudent"),
            ("admissions", "view_batch"),
            ("admissions", "view_faculty"),
            ("admissions", "view_academiclevel"),
            ("AdmissionReports", "view_admissionreports"),
            ("accounts", "access_reports"),
        ],
        "Direct Admission Officer": [
            ("admissions", "add_application"),
            ("admissions", "view_application"),
            ("admissions", "add_admittedstudent"),
            ("admissions", "change_admittedstudent"),
            ("admissions", "view_admittedstudent"),
            ("admissions", "view_batch"),
            ("admissions", "view_faculty"),
            ("admissions", "view_academiclevel"),
        ],
        "Document Verification Officer": [
            ("admissions", "view_admittedstudent"),
            ("admissions", "verify_physical_documents"),
            ("AdmissionReports", "view_admissionreports"),
            ("accounts", "access_reports"),
        ],
        "Admissions Reports Officer": [
            ("AdmissionReports", "view_admissionreports"),
            ("accounts", "access_reports"),
            ("admissions", "view_application"),
            ("admissions", "view_admittedstudent"),
            ("admissions", "view_batch"),
            ("admissions", "view_faculty"),
            ("admissions", "view_academiclevel"),
        ],
        "Student ID Officer": [
            ("admissions", "view_admittedstudent"),
            ("admissions", "change_admittedstudent"),
            ("admissions", "view_application"),
        ],
    }

    for group_name, perms in matrix.items():
        group, _ = Group.objects.get_or_create(name=group_name)
        for app_label, codename in perms:
            perm = _get_permission(Permission, app_label, codename)
            if perm:
                group.permissions.add(perm)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0023_seed_verify_physical_documents_permission"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("admissions", "0054_physical_document_verification"),
        ("AdmissionReports", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_admissions_custom_roles, noop_reverse),
    ]

