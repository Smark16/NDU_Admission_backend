"""Seed AR Data Clerk admissions role and repair portal flags for existing clerks."""
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


AR_DATA_CLERK_PERMISSIONS = (
    ("accounts", "access_admissions"),
    ("accounts", "manage_direct_applications"),
    ("admissions", "add_application"),
    ("admissions", "view_application"),
    ("admissions", "change_application"),
    ("admissions", "view_admittedstudent"),
    ("admissions", "view_batch"),
    ("admissions", "view_faculty"),
    ("admissions", "view_academiclevel"),
    ("payments", "view_applicationpayment"),
    ("accounts", "view_user"),
)


def seed_ar_data_clerk_role(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    for app_name in ("accounts", "admissions", "payments"):
        app_config = django_apps.get_app_config(app_name)
        create_contenttypes(app_config, verbosity=0, interactive=False, using=db_alias)
        create_permissions(app_config, verbosity=0, interactive=False, using=db_alias)

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    User = apps.get_model("accounts", "User")

    group, _ = Group.objects.get_or_create(name="AR Data Clerk")
    for app_label, codename in AR_DATA_CLERK_PERMISSIONS:
        perm = _get_permission(Permission, app_label, codename)
        if perm:
            group.permissions.add(perm)

    # Merge common typo group names into the canonical role.
    for alias in ("AR DATA CLARK", "AR DATA CLERK", "AR Data Clark"):
        legacy = Group.objects.filter(name__iexact=alias).exclude(pk=group.pk).first()
        if not legacy:
            continue
        for user in User.objects.filter(groups=legacy):
            user.groups.remove(legacy)
            user.groups.add(group)

    # Repair portal flags for anyone on this role (or legacy name variants).
    clerk_groups = Group.objects.filter(name__icontains="ar data")
    for user in User.objects.filter(groups__in=clerk_groups).distinct():
        user.is_staff = True
        user.is_student = False
        user.is_applicant = False
        user.portal_mode = "admin"
        user.save(update_fields=["is_staff", "is_student", "is_applicant", "portal_mode"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0039_seed_university_portal_name"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(seed_ar_data_clerk_role, noop_reverse),
    ]
