"""Create or refresh all predefined examinations Django groups."""
from django.apps import apps as django_apps
from django.contrib.auth.management import create_permissions
from django.contrib.contenttypes.management import create_contenttypes
from django.core.management.base import BaseCommand

from examinations.role_setup import EXAMINATION_ROLE_MATRIX, seed_all_examination_roles


class Command(BaseCommand):
    help = (
        "Create/update examinations groups: Examination Manager (full) and lighter "
        "office roles (Marks Officer, Results Publisher, Timetable, Retakes, Grade Reviewer)."
    )

    def handle(self, *args, **options):
        for app_name in ("accounts", "examinations"):
            app_config = django_apps.get_app_config(app_name)
            create_contenttypes(app_config, verbosity=0, interactive=False)
            create_permissions(app_config, verbosity=0, interactive=False)

        from django.contrib.auth.models import Group, Permission

        seed_all_examination_roles(Group, Permission, stdout=self.stdout)
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Roles seeded:"))
        for name in EXAMINATION_ROLE_MATRIX:
            self.stdout.write(f"  - {name}")
        self.stdout.write(
            self.style.SUCCESS(
                "\nAssign users via User Management (staff account required). "
                "Users must log out and back in after role changes."
            )
        )
