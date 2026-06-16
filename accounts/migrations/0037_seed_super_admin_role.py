from django.db import migrations


def seed_super_admin(apps, schema_editor):
    from django.contrib.auth.models import Group, Permission

    from accounts.super_admin import seed_super_admin_role

    seed_super_admin_role(Group, Permission)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0036_user_portal_mode_student"),
    ]

    operations = [
        migrations.RunPython(seed_super_admin, noop_reverse),
    ]
