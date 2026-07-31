from django.db import migrations


def sync_hod_role(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    from admissions.hod_role_setup import seed_hod_role

    seed_hod_role(Group, Permission)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0054_exemption_score_and_documents"),
    ]

    operations = [
        migrations.RunPython(sync_hod_role, noop_reverse),
    ]
