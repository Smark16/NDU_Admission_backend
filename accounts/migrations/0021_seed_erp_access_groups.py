from django.apps import apps as django_apps
from django.contrib.auth.management import create_permissions
from django.contrib.contenttypes.management import create_contenttypes
from django.db import migrations


def seed_erp_groups(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    app_config = django_apps.get_app_config("accounts")
    create_contenttypes(app_config, verbosity=0, interactive=False, using=db_alias)
    create_permissions(app_config, verbosity=0, interactive=False, using=db_alias)

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    ct = ContentType.objects.get(app_label="accounts", model="erpaccesspolicy")

    matrix = {
        "ERP System Administrator": [
            "access_admissions",
            "access_academics",
            "access_finance",
            "access_reports",
            "access_user_management",
            "access_audit",
            "access_system_settings",
            "access_lecturer_portal",
            "manage_direct_applications",
            "approve_admissions",
            "manage_batches",
            "assign_roles",
            "manage_payment_reconciliation",
        ],
        "Admissions Officer": [
            "access_admissions",
            "access_reports",
            "manage_direct_applications",
            "approve_admissions",
        ],
        "Registry / Academic Officer": [
            "access_academics",
            "access_admissions",
            "manage_batches",
            "access_system_settings",
        ],
        "Registration Officer": [
            "access_academics",
            "access_finance",
        ],
        "Finance Officer": [
            "access_finance",
            "access_reports",
            "manage_payment_reconciliation",
        ],
        "Academic Registrar": [
            "access_academics",
            "access_admissions",
            "access_reports",
            "approve_admissions",
            "assign_roles",
        ],
        "Reports Viewer": [
            "access_reports",
        ],
    }

    codenames = sorted({c for codes in matrix.values() for c in codes})
    perm_map = {
        c: Permission.objects.get(content_type=ct, codename=c) for c in codenames
    }

    for group_name, codes in matrix.items():
        group, _ = Group.objects.get_or_create(name=group_name)
        for c in codes:
            group.permissions.add(perm_map[c])

    lecturer, _ = Group.objects.get_or_create(name="Lecturer")
    lecturer.permissions.add(perm_map["access_lecturer_portal"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0020_erpaccesspolicy"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(seed_erp_groups, noop_reverse),
    ]
