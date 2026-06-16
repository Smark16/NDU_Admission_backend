from django.db import migrations


def sync_faculty_dean_viewer_role(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    from admissions.faculty_dean_role_setup import seed_faculty_dean_role

    seed_faculty_dean_role(Group, Permission)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0037_seed_faculty_dean_role"),
    ]

    operations = [
        migrations.RunPython(sync_faculty_dean_viewer_role, noop_reverse),
    ]
