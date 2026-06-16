from django.db import migrations


def sync_faculty_admin_role(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    from admissions.faculty_admin_role_setup import seed_faculty_admin_role

    seed_faculty_admin_role(Group, Permission)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0039_faculty_dean_trim_setup_perms"),
    ]

    operations = [
        migrations.RunPython(sync_faculty_admin_role, noop_reverse),
    ]
