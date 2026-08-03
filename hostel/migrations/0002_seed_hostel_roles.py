from django.apps import apps as django_apps
from django.contrib.auth.management import create_permissions
from django.contrib.contenttypes.management import create_contenttypes
from django.db import migrations


def seed_roles(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    for app_name in ("accounts", "hostel", "admissions"):
        app_config = django_apps.get_app_config(app_name)
        create_contenttypes(app_config, verbosity=0, interactive=False, using=db_alias)
        create_permissions(app_config, verbosity=0, interactive=False, using=db_alias)

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    from hostel.role_setup import seed_all_hostel_roles

    seed_all_hostel_roles(Group, Permission)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("hostel", "0001_hostel_module_initial"),
        ("accounts", "0045_hostel_module_initial"),
    ]

    operations = [
        migrations.RunPython(seed_roles, noop),
    ]
