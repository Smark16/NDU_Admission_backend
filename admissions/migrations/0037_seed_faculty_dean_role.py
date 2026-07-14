from django.apps import apps as django_apps
from django.contrib.auth.management import create_permissions
from django.contrib.contenttypes.management import create_contenttypes
from django.db import migrations


def seed_faculty_dean_role(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    for app_name in ("accounts", "admissions"):
        app_config = django_apps.get_app_config(app_name)
        create_contenttypes(app_config, verbosity=0, interactive=False, using=db_alias)
        create_permissions(app_config, verbosity=0, interactive=False, using=db_alias)

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    from admissions.faculty_dean_role_setup import seed_faculty_dean_role as _seed

    _seed(Group, Permission)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0036_alter_application_program_choices_confirmed_at"),
        ("accounts", "0033_user_assigned_faculties"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(seed_faculty_dean_role, noop_reverse),
    ]
