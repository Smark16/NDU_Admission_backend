from django.apps import apps as django_apps
from django.contrib.auth.management import create_permissions
from django.contrib.contenttypes.management import create_contenttypes
from django.db import migrations


def seed_all_examination_roles_migration(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    for app_name in ("accounts", "examinations"):
        app_config = django_apps.get_app_config(app_name)
        create_contenttypes(app_config, verbosity=0, interactive=False, using=db_alias)
        create_permissions(app_config, verbosity=0, interactive=False, using=db_alias)

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    from examinations.role_setup import seed_all_examination_roles

    seed_all_examination_roles(Group, Permission)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("examinations", "0004_seed_examination_manager_role"),
    ]

    operations = [
        migrations.RunPython(seed_all_examination_roles_migration, noop_reverse),
    ]
