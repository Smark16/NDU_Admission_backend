from django.apps import apps as django_apps
from django.contrib.auth.management import create_permissions
from django.contrib.contenttypes.management import create_contenttypes
from django.db import migrations


def seed_examination_manager(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    for app_name in ("accounts", "examinations"):
        app_config = django_apps.get_app_config(app_name)
        create_contenttypes(app_config, verbosity=0, interactive=False, using=db_alias)
        create_permissions(app_config, verbosity=0, interactive=False, using=db_alias)

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    from examinations.role_setup import seed_examination_manager_group

    seed_examination_manager_group(Group, Permission)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("examinations", "0003_courseunitresult_edit_unlocked_and_more"),
        ("accounts", "0029_access_examinations_permission"),
    ]

    operations = [
        migrations.RunPython(seed_examination_manager, noop_reverse),
    ]
