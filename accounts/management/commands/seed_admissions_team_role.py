"""Create/refresh the Admissions Team role (Admissions module only)."""
from django.apps import apps as django_apps
from django.contrib.auth.management import create_permissions
from django.contrib.contenttypes.management import create_contenttypes
from django.core.management.base import BaseCommand

from accounts.admissions_team_role_setup import ROLE_NAME, seed_admissions_team_role


class Command(BaseCommand):
    help = (
        "Create or refresh Admissions Team: Admissions module only — applications, "
        "admit/revoke, offer letters, intakes, templates, reports. "
        "Finance, Academics, Enrollment admin, and User Admin stay blocked."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-repair-users",
            action="store_true",
            help="Do not reset is_staff / portal_mode flags on users in this role.",
        )

    def handle(self, *args, **options):
        for app_name in (
            "accounts",
            "admissions",
            "payments",
            "AdmissionLetter",
            "AdmissionReports",
            "Drafts",
        ):
            try:
                app_config = django_apps.get_app_config(app_name)
            except LookupError:
                continue
            create_contenttypes(app_config, verbosity=0, interactive=False)
            create_permissions(app_config, verbosity=0, interactive=False)

        self.stdout.write(f"Seeding {ROLE_NAME}...")
        seed_admissions_team_role(
            stdout=self.stdout,
            repair_users=not options["no_repair_users"],
        )
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"{ROLE_NAME} ready."))
        self.stdout.write(
            "Assign users in Admin > User Management > Users. "
            "They must log out and back in after role changes."
        )
