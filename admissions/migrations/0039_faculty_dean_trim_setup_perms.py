from django.db import migrations


def sync_faculty_dean_menu_permissions(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    from admissions.faculty_dean_role_setup import seed_faculty_dean_role

    seed_faculty_dean_role(Group, Permission)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0038_faculty_dean_viewer_only"),
    ]

    operations = [
        migrations.RunPython(sync_faculty_dean_menu_permissions, noop_reverse),
    ]
