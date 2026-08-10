"""Create/refresh the AR Data Clerk role (admissions data entry, no admit)."""
from django.apps import apps as django_apps
from django.contrib.auth.management import create_permissions
from django.contrib.contenttypes.management import create_contenttypes
from django.core.management.base import BaseCommand

from accounts.ar_data_clerk_role_setup import ROLE_NAME, seed_ar_data_clerk_role


class Command(BaseCommand):
    help = (
        "Create or refresh the AR Data Clerk role: direct applications and "
        "view admitted students, but cannot admit / revoke / verify docs / enroll."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-repair-users",
            action="store_true",
            help="Do not reset is_staff / portal_mode flags on users in this role.",
        )

    def handle(self, *args, **options):
        for app_name in ("accounts", "admissions", "payments", "Programs"):
            try:
                app_config = django_apps.get_app_config(app_name)
            except LookupError:
                continue
            create_contenttypes(app_config, verbosity=0, interactive=False)
            create_permissions(app_config, verbosity=0, interactive=False)

        self.stdout.write(f"Seeding {ROLE_NAME}...")
        seed_ar_data_clerk_role(
            stdout=self.stdout,
            repair_users=not options["no_repair_users"],
        )
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"{ROLE_NAME} ready."))
        self.stdout.write(
            "Assign users in Admin → User Management → Users. "
            "They must log out and back in after role changes."
        )
        self.stdout.write(
            "This role can manage direct applications and view students, "
            "but cannot admit applicants."
        )
