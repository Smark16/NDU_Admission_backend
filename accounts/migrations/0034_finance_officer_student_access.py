from django.db import migrations


def sync_finance_student_access_roles(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    from accounts.erp_role_setup import seed_erp_team_role_group

    seed_erp_team_role_group(Group, Permission, "Finance Officer")
    seed_erp_team_role_group(Group, Permission, "Finance Manager")


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0033_user_assigned_faculties"),
    ]

    operations = [
        migrations.RunPython(sync_finance_student_access_roles, noop_reverse),
    ]
