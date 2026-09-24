from django.apps import apps as global_apps
from django.db import migrations


def sync_roles(apps, schema_editor):
    """Redo of 0075 -- that migration's RunPython ran before Django's
    post_migrate signal had created the new examinations.review_marks_hod /
    review_marks_dean / review_result_changes_hod / review_result_changes_dean
    Permission rows, so seed_hod_role/seed_faculty_dean_role silently found
    nothing to add for those codenames. Force permission creation for the
    affected apps first, then reseed."""
    from django.contrib.auth.management import create_permissions

    for app_label in ("examinations", "admissions"):
        create_permissions(global_apps.get_app_config(app_label), verbosity=0)

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    from admissions.hod_role_setup import seed_hod_role
    from admissions.faculty_dean_role_setup import seed_faculty_dean_role
    from admissions.exam_coordinator_role_setup import seed_exam_coordinator_role

    seed_hod_role(Group, Permission)
    seed_faculty_dean_role(Group, Permission)
    seed_exam_coordinator_role(Group, Permission)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0075_seed_exam_marks_review_roles"),
    ]

    operations = [
        migrations.RunPython(sync_roles, noop_reverse),
    ]
