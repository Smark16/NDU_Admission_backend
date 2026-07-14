"""Create or refresh all predefined ERP team Django groups."""
from django.apps import apps as django_apps
from django.contrib.auth.management import create_permissions
from django.contrib.contenttypes.management import create_contenttypes
from django.core.management.base import BaseCommand

from accounts.erp_role_setup import ERP_TEAM_ROLE_MATRIX, PERMISSION_APPS, seed_all_erp_team_roles
from accounts.super_admin import seed_super_admin_role


class Command(BaseCommand):
    help = (
        "Create/update Finance, Academics, User Admin, and Audit team groups. "
        "Admissions, Examinations, and Graduation roles are seeded separately "
        "(migrations or seed_examination_manager_role / seed_graduation_roles)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--all-modules",
            action="store_true",
            help="Also re-seed Examinations and Graduation roles.",
        )

    def handle(self, *args, **options):
        for app_name in PERMISSION_APPS:
            app_config = django_apps.get_app_config(app_name)
            create_contenttypes(app_config, verbosity=0, interactive=False)
            create_permissions(app_config, verbosity=0, interactive=False)

        from django.contrib.auth.models import Group, Permission

        seed_all_erp_team_roles(Group, Permission, stdout=self.stdout)
        self.stdout.write("")
        self.stdout.write("Seeding Super Admin (all permissions)...")
        seed_super_admin_role(Group, Permission, stdout=self.stdout)

        if options["all_modules"]:
            self.stdout.write("")
            self.stdout.write("Re-seeding Examinations and Graduation roles...")
            from examinations.role_setup import seed_all_examination_roles
            from graduation.role_setup import seed_all_graduation_roles

            seed_all_examination_roles(Group, Permission, stdout=self.stdout)
            seed_all_graduation_roles(Group, Permission, stdout=self.stdout)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Team roles seeded:"))
        for name in ERP_TEAM_ROLE_MATRIX:
            self.stdout.write(f"  - {name}")
        self.stdout.write("  - Super Admin")
        self.stdout.write(
            self.style.SUCCESS(
                "\nAssign users in Admin > User Management > Users. "
                "Users must log out and back in after role changes."
            )
        )
